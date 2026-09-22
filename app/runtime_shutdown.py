from __future__ import annotations

from datetime import datetime, timezone
import logging
import secrets
import threading
from typing import Callable

import requests
from flask import Flask, Response, g, request
from sqlalchemy import select

from app.config import Config
from app.extensions import db
from app.integrations.selora.client import SeloraApiClient
from app.models.import_workspace import ImportWorkspace
from app.repositories.import_workspace_repository import ImportWorkspaceRepository
from app.services.client_instance_identity_service import ClientInstanceIdentityService
from app.services.remote_workspace_coordinator import RemoteWorkspaceCoordinator


logger = logging.getLogger("app")


class SafeShutdownController:
    """Coordinate a browser-triggered graceful shutdown of the desktop app."""

    def __init__(self, *, app: Flask) -> None:
        self._app = app
        self._token = secrets.token_urlsafe(32)
        self._condition = threading.Condition()
        self._active_requests = 0
        self._shutting_down = False
        self._shutdown_callable: Callable[[], None] | None = None
        self._worker: threading.Thread | None = None

    def install(self) -> None:
        self._app.jinja_env.globals["safe_exit_token"] = self._token

        @self._app.before_request
        def _track_request_start():
            with self._condition:
                if (
                    self._shutting_down
                    and request.endpoint != "runtime_safe_exit"
                ):
                    return Response(
                        "برنامه در حال خروج امن است.",
                        status=503,
                        content_type="text/plain; charset=utf-8",
                    )

                # Count the exit request too. The shutdown worker therefore
                # waits until the 202 response is fully finalized before it
                # stops the WSGI server.
                self._active_requests += 1
                g._selora_runtime_counted_request = True
            return None

        @self._app.teardown_request
        def _track_request_end(_error) -> None:
            if not getattr(g, "_selora_runtime_counted_request", False):
                return
            with self._condition:
                self._active_requests = max(0, self._active_requests - 1)
                self._condition.notify_all()

        @self._app.post("/system/exit", endpoint="runtime_safe_exit")
        def _safe_exit() -> Response:
            if not self._request_is_allowed():
                return Response(
                    "درخواست خروج معتبر نیست.",
                    status=403,
                    content_type="text/plain; charset=utf-8",
                )

            started = self.request_shutdown()
            message = (
                "خروج امن شروع شد. برنامه پس از پایان عملیات جاری، آزاد کردن "
                "قفل‌های سلورا و بستن دیتابیس متوقف می‌شود. می‌توانید این تب را ببندید."
                if started
                else "خروج امن از قبل در حال انجام است. می‌توانید این تب را ببندید."
            )
            return Response(
                _shutdown_page(message),
                status=202,
                content_type="text/html; charset=utf-8",
            )

    def bind_server_shutdown(self, shutdown_callable: Callable[[], None]) -> None:
        self._shutdown_callable = shutdown_callable

    def wait(self) -> None:
        worker = self._worker
        if worker is not None:
            worker.join()

    def request_shutdown(self) -> bool:
        with self._condition:
            if self._shutting_down:
                return False
            self._shutting_down = True

        self._worker = threading.Thread(
            target=self._shutdown_worker,
            name="safe-shutdown",
            daemon=True,
        )
        self._worker.start()
        return True

    def _request_is_allowed(self) -> bool:
        remote = (request.remote_addr or "").strip()
        if remote not in {"127.0.0.1", "::1"}:
            return False
        return secrets.compare_digest(
            request.form.get("token", ""),
            self._token,
        )

    def _shutdown_worker(self) -> None:
        logger.info("Safe shutdown requested")

        # Wait for send/crawl/autosave/heartbeat requests to finish. New
        # requests are rejected from this point forward.
        with self._condition:
            while self._active_requests > 0:
                logger.info(
                    "Safe shutdown waiting for active requests: count=%s",
                    self._active_requests,
                )
                self._condition.wait(timeout=1.0)

        try:
            self._release_remote_locks()
        except Exception:
            logger.exception("Safe shutdown could not release every remote lock")

        try:
            with self._app.app_context():
                db.session.remove()
        except Exception:
            logger.exception("Safe shutdown database session cleanup failed")

        logger.info("Safe shutdown cleanup complete")
        if self._shutdown_callable is not None:
            self._shutdown_callable()

    def _release_remote_locks(self) -> None:
        with self._app.app_context():
            workspaces = list(
                db.session.scalars(
                    select(ImportWorkspace)
                    .where(ImportWorkspace.remote_lock_token.is_not(None))
                ).all()
            )

            if not workspaces:
                logger.info("Safe shutdown: no remote locks to release")
                return

            client_instance_id = ClientInstanceIdentityService(
                path=Config.CLIENT_INSTANCE_ID_FILE,
            ).get_or_create()

            # Exit should remain bounded even if the network is broken. We pass
            # an explicit plain Session so the normal runtime retry injection is
            # not used during shutdown. Remote locks also have server-side TTL.
            client = SeloraApiClient(
                base_url=Config.SELORA_API_BASE_URL,
                api_key=Config.SELORA_API_KEY,
                connect_timeout_seconds=min(
                    Config.SELORA_API_CONNECT_TIMEOUT_SECONDS,
                    3,
                ),
                read_timeout_seconds=min(
                    Config.SELORA_API_READ_TIMEOUT_SECONDS,
                    5,
                ),
                http_session=requests.Session(),
            )
            repository = ImportWorkspaceRepository()
            coordinator = RemoteWorkspaceCoordinator(
                client=client,
                repository=repository,
                client_instance_id=client_instance_id,
            )

            for workspace in workspaces:
                try:
                    if workspace.has_active_remote_lease:
                        coordinator.release(workspace=workspace)
                        logger.info(
                            "Safe shutdown released remote lock: workspace_id=%s",
                            workspace.id,
                        )
                    else:
                        workspace.remote_lock_token = None
                        workspace.remote_lock_expires_at = None
                        workspace.remote_status_updated_at = datetime.now(timezone.utc)
                        repository.commit()
                except Exception:
                    db.session.rollback()
                    # Do not preserve a stale local lock if the API is offline;
                    # the server-side lock will expire according to its TTL.
                    refreshed = db.session.get(ImportWorkspace, workspace.id)
                    if refreshed is not None:
                        refreshed.remote_lock_token = None
                        refreshed.remote_lock_expires_at = None
                        refreshed.remote_status_updated_at = datetime.now(timezone.utc)
                        repository.commit()
                    logger.exception(
                        "Safe shutdown remote lock release failed: workspace_id=%s",
                        workspace.id,
                    )


def _shutdown_page(message: str) -> str:
    return f"""<!doctype html>
<html lang=\"fa\" dir=\"rtl\">
<head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>خروج امن</title></head>
<body style=\"font-family:system-ui,sans-serif;background:#f8fafc;color:#111827;margin:0;padding:40px\">
  <main style=\"max-width:680px;margin:10vh auto;background:white;border:1px solid #e5e7eb;border-radius:20px;padding:28px;line-height:2\">
    <h1 style=\"margin-top:0\">خروج امن Selora Importer</h1>
    <p>{message}</p>
  </main>
</body>
</html>"""
