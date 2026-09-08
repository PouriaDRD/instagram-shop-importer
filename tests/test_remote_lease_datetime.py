from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.import_workspace import (
    ImportWorkspace,
)


def _workspace() -> ImportWorkspace:
    workspace = ImportWorkspace(
        source_id="source-1",
    )
    workspace.remote_lock_token = (
        "550e8400-e29b-41d4-a716-446655440000"
    )
    return workspace


def test_active_remote_lease_accepts_sqlite_naive_utc_datetime() -> None:
    workspace = _workspace()
    workspace.remote_lock_expires_at = (
        datetime.utcnow()
        + timedelta(
            minutes=5
        )
    )

    assert (
        workspace.has_active_remote_lease
        is True
    )


def test_expired_remote_lease_accepts_sqlite_naive_utc_datetime() -> None:
    workspace = _workspace()
    workspace.remote_lock_expires_at = (
        datetime.utcnow()
        - timedelta(
            minutes=5
        )
    )

    assert (
        workspace.has_active_remote_lease
        is False
    )


def test_active_remote_lease_still_accepts_aware_datetime() -> None:
    workspace = _workspace()
    workspace.remote_lock_expires_at = (
        datetime.now(
            timezone.utc
        )
        + timedelta(
            minutes=5
        )
    )

    assert (
        workspace.has_active_remote_lease
        is True
    )
