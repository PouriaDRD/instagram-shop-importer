"""Ensure the Windows startup migrator covers the product metadata schema."""
from sqlalchemy import create_engine, inspect

from app.runtime_database import (
    FINAL_REVISION,
    _apply_sqlite_schema_migrations,
    _sqlite_needs_migration,
)


def test_legacy_sqlite_is_upgraded_with_catalog_fields_and_current_revision():
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE crawled_media (id INTEGER PRIMARY KEY)")
            connection.exec_driver_sql("CREATE TABLE crawled_assets (id INTEGER PRIMARY KEY)")
            connection.exec_driver_sql("CREATE TABLE import_drafts (id INTEGER PRIMARY KEY, status VARCHAR(32))")
            connection.exec_driver_sql("CREATE TABLE import_draft_product_data (id INTEGER PRIMARY KEY)")
        assert _sqlite_needs_migration(engine) is True
        _apply_sqlite_schema_migrations(engine)
        inspector = inspect(engine)
        columns = {col["name"] for col in inspector.get_columns("import_draft_product_data")}
        assert {"benefits", "slug", "category_id", "subcategory_id"} <= columns
        with engine.connect() as connection:
            revision = connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
        assert revision == FINAL_REVISION == "f5c100000001"
        assert _sqlite_needs_migration(engine) is False
        _apply_sqlite_schema_migrations(engine)  # safe on repeat
        assert _sqlite_needs_migration(engine) is False
    finally:
        engine.dispose()
