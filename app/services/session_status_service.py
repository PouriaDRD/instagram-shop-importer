from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from flask import Flask, g
from sqlalchemy import select

from app.extensions import db
from app.models.import_workspace import ImportWorkspace


@dataclass(frozen=True, slots=True)
class SessionSeloraStatus:
    sync_status: str
    sync_label: str
    badge_class: str
    workflow_status: str
    workflow_label: str | None
    last_synced_at: datetime | None
    error: str | None
    has_remote_workspace: bool


_SYNC_LABELS: dict[str, tuple[str, str]] = {
    "pending": ("ارسال نشده", "pending"),
    "syncing": ("در حال ارسال به سلورا", "running"),
    "synced": ("ارسال‌شده به سلورا", "completed"),
    "error": ("خطا در آخرین ارسال", "failed"),
}

_WORKFLOW_LABELS: dict[str, str] = {
    "needs_review": "در انتظار بررسی در سلورا",
    "changes_requested": "نیازمند اصلاح",
    "approved": "تأیید شده",
    "importing": "در حال ورود به فروشگاه",
    "imported": "وارد شده به فروشگاه",
    "rejected": "رد شده",
}


def register_session_status_helpers(app: Flask) -> None:
    app.jinja_env.globals["session_selora_status"] = session_selora_status


def session_selora_status(source_id: str) -> SessionSeloraStatus:
    cache = getattr(g, "_session_selora_status_cache", None)
    if cache is None:
        # One lightweight query for the whole sessions page instead of one
        # query per row.
        workspaces = list(
            db.session.scalars(
                select(ImportWorkspace).order_by(
                    ImportWorkspace.created_at.asc(),
                    ImportWorkspace.id.asc(),
                )
            ).all()
        )
        canonical_by_source: dict[str, ImportWorkspace] = {}
        for item in workspaces:
            canonical_by_source.setdefault(item.source_id, item)
        cache = {
            key: _status_from_workspace(value)
            for key, value in canonical_by_source.items()
        }
        g._session_selora_status_cache = cache

    cached = cache.get(source_id)
    if cached is not None:
        return cached

    result = SessionSeloraStatus(
        sync_status="pending",
        sync_label="ارسال نشده",
        badge_class="pending",
        workflow_status="unknown",
        workflow_label=None,
        last_synced_at=None,
        error=None,
        has_remote_workspace=False,
    )
    cache[source_id] = result
    return result


def _status_from_workspace(workspace: ImportWorkspace) -> SessionSeloraStatus:
    status = (workspace.local_sync_status or "pending").strip().lower()
    label, badge_class = _SYNC_LABELS.get(
        status,
        (f"وضعیت نامشخص: {status}", "pending"),
    )

    if status == "syncing" and workspace.last_synced_at is not None:
        label = "در حال ارسال مجدد"
    elif status == "error" and workspace.last_synced_at is None:
        label = "ارسال ناموفق"

    workflow_status = (
        workspace.remote_workflow_status or "unknown"
    ).strip().lower()

    return SessionSeloraStatus(
        sync_status=status,
        sync_label=label,
        badge_class=badge_class,
        workflow_status=workflow_status,
        workflow_label=_WORKFLOW_LABELS.get(workflow_status),
        last_synced_at=workspace.last_synced_at,
        error=workspace.last_sync_error,
        has_remote_workspace=bool(workspace.remote_workspace_id),
    )
