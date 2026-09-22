from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps
import logging

from app.extensions import db
from app.integrations.selora.client import SeloraApiError
from app.models.import_workspace import ImportWorkspace, LocalSyncStatus
from app.services.selora_import_service import SeloraImportService
from app.services.remote_workspace_coordinator import RemoteWorkspaceCoordinator


logger = logging.getLogger(__name__)


def install_import_status_tracking() -> None:
    """Persist the real Selora-send state independently from crawl status."""
    if getattr(SeloraImportService, "_selora_status_tracking_installed", False):
        return

    original_send = SeloraImportService.send

    @wraps(original_send)
    def _tracked_send(self, *, draft, crawl_session, client_instance_id):
        _update_status(
            workspace_id=draft.id,
            status=LocalSyncStatus.SYNCING.value,
            error=None,
        )

        try:
            result = original_send(
                self,
                draft=draft,
                crawl_session=crawl_session,
                client_instance_id=client_instance_id,
            )
        except Exception as exc:
            db.session.rollback()
            message = _operator_error(exc)
            _update_status(
                workspace_id=draft.id,
                status=LocalSyncStatus.ERROR.value,
                error=message,
            )
            logger.warning(
                "Selora send marked as failed: workspace_id=%s error=%s",
                draft.id,
                message,
            )
            raise

        _update_status(
            workspace_id=draft.id,
            status=LocalSyncStatus.SYNCED.value,
            error=None,
            synced_at=datetime.now(timezone.utc),
        )
        return result

    SeloraImportService.send = _tracked_send  # type: ignore[method-assign]

    original_ensure = RemoteWorkspaceCoordinator.ensure_mutation_allowed

    @wraps(original_ensure)
    def _tracked_ensure(self, *, workspace):
        try:
            return original_ensure(self, workspace=workspace)
        except SeloraApiError as exc:
            # The send route validates the remote workspace before it calls
            # SeloraImportService.send(). Persist connectivity/API failures
            # from that preflight as the latest send error too.
            db.session.rollback()
            _update_status(
                workspace_id=workspace.id,
                status=LocalSyncStatus.ERROR.value,
                error=_operator_error(exc),
            )
            raise

    RemoteWorkspaceCoordinator.ensure_mutation_allowed = _tracked_ensure  # type: ignore[method-assign]
    setattr(SeloraImportService, "_selora_status_tracking_installed", True)


def _update_status(
    *,
    workspace_id: str,
    status: str,
    error: str | None,
    synced_at: datetime | None = None,
) -> None:
    try:
        workspace = db.session.get(ImportWorkspace, workspace_id)
        if workspace is None:
            return

        workspace.local_sync_status = status
        workspace.last_sync_error = error
        if synced_at is not None:
            workspace.last_synced_at = synced_at
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception(
            "Could not persist Selora send status: workspace_id=%s status=%s",
            workspace_id,
            status,
        )


def _operator_error(exc: Exception) -> str:
    text = str(exc).strip()
    if isinstance(exc, SeloraApiError):
        return text or exc.__class__.__name__
    if text:
        return f"{exc.__class__.__name__}: {text}"
    return exc.__class__.__name__
