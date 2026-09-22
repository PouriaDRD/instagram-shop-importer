from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path
import sqlite3

from flask import Flask
from sqlalchemy import event, inspect
from sqlalchemy.engine import Engine

from app.extensions import db


logger = logging.getLogger("app")

FINAL_REVISION = "d2f4a8e71c90"

_REQUIRED_COLUMNS: dict[str, set[str]] = {
    "crawled_media": {
        "is_available",
        "last_seen_at",
    },
    "crawled_assets": {
        "is_available",
        "last_seen_at",
        "local_file_path",
        "local_file_status",
        "local_saved_at",
        "local_content_type",
        "local_file_size",
        "local_sha256",
        "local_file_error",
    },
    "import_drafts": {
        "local_sync_status",
        "remote_workflow_status",
        "last_synced_at",
        "last_sync_error",
        "remote_status_updated_at",
        "remote_workspace_id",
        "remote_revision",
        "remote_is_editable",
        "remote_lock_token",
        "remote_lock_expires_at",
    },
}


def configure_sqlite_runtime(app: Flask) -> None:
    """Enable SQLite settings that are safer for the threaded desktop app."""
    with app.app_context():
        engine = db.engine
        if engine.dialect.name != "sqlite":
            return

        if getattr(engine, "_selora_sqlite_runtime_configured", False):
            return

        setattr(engine, "_selora_sqlite_runtime_configured", True)

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=15000")
            finally:
                cursor.close()

        # WAL lets readers coexist with the short write transactions used by
        # crawl/heartbeat/send flows.  NORMAL is the usual WAL durability
        # trade-off for a local desktop cache/database.
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            connection.exec_driver_sql("PRAGMA synchronous=NORMAL")
            connection.exec_driver_sql("PRAGMA wal_autocheckpoint=1000")
            connection.commit()

        logger.info(
            "SQLite runtime configured: journal_mode=WAL busy_timeout_ms=15000"
        )


def migrate_runtime_database(app: Flask) -> Path | None:
    """
    Bring the local database to the current schema at application startup.

    Older releases created schema with ``db.create_all()`` and therefore may
    have no Alembic version row.  This migrator is intentionally self-contained
    so it also works in a frozen PyInstaller executable where the Alembic script
    directory may not be available as ordinary files.
    """
    with app.app_context():
        engine = db.engine
        if engine.dialect.name != "sqlite":
            logger.warning(
                "Automatic runtime migration is currently implemented for SQLite only."
            )
            return None

        if not _sqlite_needs_migration(engine):
            logger.info("Database schema is current: revision=%s", FINAL_REVISION)
            return None

        backup_path = _backup_sqlite_database(app=app, engine=engine)
        if backup_path is not None:
            logger.info("Pre-migration database backup created: %s", backup_path)

        # Creates missing tables for a new or partially-created database. It
        # never alters existing tables, so legacy column work is handled below.
        db.create_all()
        _apply_sqlite_schema_migrations(engine)

        logger.info("Database migration complete: revision=%s", FINAL_REVISION)
        return backup_path


def _sqlite_needs_migration(engine: Engine) -> bool:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    if not set(_REQUIRED_COLUMNS).issubset(tables):
        return True

    for table_name, required in _REQUIRED_COLUMNS.items():
        actual = {
            column["name"]
            for column in inspector.get_columns(table_name)
        }
        if not required.issubset(actual):
            return True

    if "alembic_version" not in tables:
        return True

    with engine.connect() as connection:
        try:
            revision = connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version LIMIT 1"
            ).scalar_one_or_none()
        except Exception:
            return True

    return revision != FINAL_REVISION


def _backup_sqlite_database(*, app: Flask, engine: Engine) -> Path | None:
    raw_database = engine.url.database
    if not raw_database or raw_database == ":memory:":
        return None

    database_path = Path(raw_database)
    if not database_path.is_absolute():
        database_path = Path(app.instance_path) / database_path
    database_path = database_path.resolve()

    if not database_path.is_file() or database_path.stat().st_size <= 0:
        return None

    backup_dir = Path(app.instance_path) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"{database_path.stem}-pre-migration-{stamp}.db"

    source = sqlite3.connect(str(database_path), timeout=15)
    destination = sqlite3.connect(str(backup_path), timeout=15)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()

    return backup_path


def _apply_sqlite_schema_migrations(engine: Engine) -> None:
    with engine.begin() as connection:
        # Availability tracking (6fd43a9c2e71).
        _add_column_if_missing(
            connection,
            table="crawled_media",
            column="is_available",
            ddl="BOOLEAN NOT NULL DEFAULT 1",
        )
        _add_column_if_missing(
            connection,
            table="crawled_media",
            column="last_seen_at",
            ddl="DATETIME",
        )
        _add_column_if_missing(
            connection,
            table="crawled_assets",
            column="is_available",
            ddl="BOOLEAN NOT NULL DEFAULT 1",
        )
        _add_column_if_missing(
            connection,
            table="crawled_assets",
            column="last_seen_at",
            ddl="DATETIME",
        )

        # Workspace sync/workflow state (38b4db7f30c2).
        for column, ddl in (
            ("local_sync_status", "VARCHAR(32) NOT NULL DEFAULT 'pending'"),
            ("remote_workflow_status", "VARCHAR(32) NOT NULL DEFAULT 'unknown'"),
            ("last_synced_at", "DATETIME"),
            ("last_sync_error", "TEXT"),
            ("remote_status_updated_at", "DATETIME"),
        ):
            _add_column_if_missing(
                connection,
                table="import_drafts",
                column=column,
                ddl=ddl,
            )

        connection.exec_driver_sql(
            "UPDATE import_drafts "
            "SET local_sync_status = 'synced' "
            "WHERE status = 'sent' AND local_sync_status = 'pending'"
        )

        # Remote coordination fields (7b51f8f31b0a).
        for column, ddl in (
            ("remote_workspace_id", "VARCHAR(36)"),
            ("remote_revision", "INTEGER"),
            ("remote_is_editable", "BOOLEAN"),
            ("remote_lock_token", "VARCHAR(36)"),
            ("remote_lock_expires_at", "DATETIME"),
        ):
            _add_column_if_missing(
                connection,
                table="import_drafts",
                column=column,
                ddl=ddl,
            )

        # Cache -> persistent-storage field rename (c9d... + d2f...).
        for old_name, new_name in (
            ("local_cache_path", "local_file_path"),
            ("local_cache_status", "local_file_status"),
            ("local_cached_at", "local_saved_at"),
            ("local_cache_error", "local_file_error"),
        ):
            _rename_column_if_needed(
                connection,
                table="crawled_assets",
                old_name=old_name,
                new_name=new_name,
            )

        for column, ddl in (
            ("local_file_path", "TEXT"),
            ("local_file_status", "VARCHAR(32) NOT NULL DEFAULT 'missing'"),
            ("local_saved_at", "DATETIME"),
            ("local_content_type", "VARCHAR(255)"),
            ("local_file_size", "INTEGER"),
            ("local_sha256", "VARCHAR(64)"),
            ("local_file_error", "TEXT"),
        ):
            _add_column_if_missing(
                connection,
                table="crawled_assets",
                column=column,
                ddl=ddl,
            )

        # Idempotent indexes created by the migration chain.
        for statement in (
            "CREATE INDEX IF NOT EXISTS ix_crawled_media_is_available "
            "ON crawled_media (is_available)",
            "CREATE INDEX IF NOT EXISTS ix_crawled_media_last_seen_at "
            "ON crawled_media (last_seen_at)",
            "CREATE INDEX IF NOT EXISTS ix_crawled_assets_is_available "
            "ON crawled_assets (is_available)",
            "CREATE INDEX IF NOT EXISTS ix_crawled_assets_last_seen_at "
            "ON crawled_assets (last_seen_at)",
            "CREATE INDEX IF NOT EXISTS ix_import_drafts_local_sync_status "
            "ON import_drafts (local_sync_status)",
            "CREATE INDEX IF NOT EXISTS ix_import_drafts_remote_workflow_status "
            "ON import_drafts (remote_workflow_status)",
            "CREATE INDEX IF NOT EXISTS ix_import_drafts_remote_workspace_id "
            "ON import_drafts (remote_workspace_id)",
        ):
            connection.exec_driver_sql(statement)

        connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS alembic_version ("
            "version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
        connection.exec_driver_sql("DELETE FROM alembic_version")
        connection.exec_driver_sql(
            "INSERT INTO alembic_version (version_num) VALUES (?)",
            (FINAL_REVISION,),
        )


def _columns(connection, table: str) -> set[str]:
    rows = connection.exec_driver_sql(
        f'PRAGMA table_info("{table}")'
    ).all()
    return {str(row[1]) for row in rows}


def _add_column_if_missing(
    connection,
    *,
    table: str,
    column: str,
    ddl: str,
) -> None:
    if column in _columns(connection, table):
        return
    connection.exec_driver_sql(
        f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl}'
    )


def _rename_column_if_needed(
    connection,
    *,
    table: str,
    old_name: str,
    new_name: str,
) -> None:
    columns = _columns(connection, table)
    if old_name not in columns or new_name in columns:
        return
    connection.exec_driver_sql(
        f'ALTER TABLE "{table}" RENAME COLUMN "{old_name}" TO "{new_name}"'
    )
