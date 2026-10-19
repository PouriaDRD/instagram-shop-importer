from __future__ import annotations

import logging
import threading

from flask import Flask

from app.crawler.instagram import (
    PlaywrightInstagramProvider,
)
from app.extensions import db
from app.repositories import (
    CrawlSessionRepository,
)
from app.services.crawl_service import (
    CrawlService,
)

logger = logging.getLogger("crawler")


class BackgroundCrawlRunner:
    def start(
        self,
        *,
        app: Flask,
        session_id: str,
        max_items: int | None,
        sort_order: str = "newest",
        auth_state_path: str | None = None,
    ) -> None:
        kwargs = {
            "app": app,
            "session_id": session_id,
            "max_items": max_items,
        }
        if sort_order != "newest":
            kwargs["sort_order"] = sort_order
        if auth_state_path is not None:
            kwargs["auth_state_path"] = auth_state_path
        registry = app.extensions.get("crawl_job_progress")
        if registry is not None:
            registry.begin(session_id)
        audits = app.extensions.get("crawl_run_audit")
        if audits is not None:
            try:
                audits.begin(session_id, requested=max_items,
                             sort_order=sort_order, signed_in=bool(auth_state_path))
            except Exception:
                if registry is not None:
                    registry.finish(session_id, "failed")
                raise
        thread = threading.Thread(
            target=self._run,
            kwargs=kwargs,
            name=f"crawl-{session_id}",
            daemon=True,
        )

        try:
            thread.start()
        except Exception:
            if registry is not None:
                registry.finish(session_id, "failed")
            if audits is not None:
                audits.finish(session_id, status="failed", error_category="thread_start")
            raise

    @staticmethod
    def _run(
        *,
        app: Flask,
        session_id: str,
        max_items: int | None,
        sort_order: str = "newest",
        auth_state_path: str | None = None,
    ) -> None:
        registry = app.extensions.get("crawl_job_progress")
        tracked = registry is not None and registry.exists(session_id)
        audits = app.extensions.get("crawl_run_audit")
        app_context = app.app_context()
        context_pushed = False

        try:
            app_context.push()
            context_pushed = True

            repository = CrawlSessionRepository()

            try:
                provider = (
                    PlaywrightInstagramProvider(auth_state_path=auth_state_path)
                    if auth_state_path is not None
                    else PlaywrightInstagramProvider()
                )
                if tracked:
                    provider.set_job_hooks(
                        check_cancel=lambda: registry.check(session_id),
                        on_progress=lambda phase, current, total:
                            registry.report(session_id, phase, current, total),
                    )
                service = CrawlService(
                    provider=provider,
                    repository=repository,
                )

                opts = {"session_id": session_id, "max_items": max_items}
                if sort_order != "newest":
                    opts["sort_order"] = sort_order
                if tracked:
                    opts["check_cancel"] = lambda: registry.check(session_id)
                    def track_progress(phase: str, current: int,
                                       total: int | None, **metrics: int) -> None:
                        registry.report(session_id, phase, current, total, **metrics)
                        if audits is None:
                            return
                        audit_values: dict[str, int] = {}
                        if phase == "downloading":
                            if total is not None:
                                audit_values["download_total"] = total
                            for old, new in (("saved", "download_saved"),
                                             ("reused", "download_reused"),
                                             ("failed", "download_failed"),
                                             ("bytes_saved", "bytes_downloaded")):
                                if old in metrics:
                                    audit_values[new] = metrics[old]
                        try:
                            audits.update(session_id, phase=phase,
                                          metrics=audit_values)
                        except Exception:
                            logger.exception("Could not persist crawl progress %s", session_id)
                    opts["on_progress"] = track_progress
                if tracked and audits is not None:
                    def audit_metrics(metrics: dict[str, int]) -> None:
                        try:
                            audits.update(session_id, metrics=metrics)
                        except Exception:
                            # Observability must not corrupt a completed crawl.
                            logger.exception("Could not update crawl audit %s", session_id)
                    opts["on_audit"] = audit_metrics
                service.run(**opts)

            except Exception as exc:
                logger.exception(
                    "Unexpected background crawl failure: %s",
                    session_id,
                )

                BackgroundCrawlRunner._recover_failed_session(
                    repository=repository,
                    session_id=session_id,
                    error=exc,
                )

        except Exception:
            logger.exception(
                (
                    "Background crawl infrastructure "
                    "failure before execution completed: %s"
                ),
                session_id,
            )

        finally:
            phase = "failed"
            if tracked:
                # An in-memory cancellation request never reports success until
                # the service has persisted its terminal SQL state.
                try:
                    # Reuse the already-pushed application context. Creating a
                    # nested one needlessly tears down the same scoped session.
                    session = CrawlSessionRepository().get(session_id=session_id)
                    phase = session.status if session else "failed"
                    registry.finish(session_id, phase)
                except Exception:
                    logger.exception("Unable to finalize crawl progress %s", session_id)
                    registry.finish(session_id, "failed")
            if audits is not None:
                try:
                    terminal = phase if tracked else "failed"
                    audits.finish(session_id, status=terminal)
                except Exception:
                    logger.exception("Unable to finalize crawl audit %s", session_id)
            if context_pushed:
                # Flask-SQLAlchemy removes the scoped session on context
                # teardown. Calling remove() here would do it twice.
                try:
                    app_context.pop()
                except Exception:
                    logger.exception(
                        (
                            "Failed to tear down application "
                            "context after crawl %s"
                        ),
                        session_id,
                    )

    @staticmethod
    def _recover_failed_session(
        *,
        repository: CrawlSessionRepository,
        session_id: str,
        error: Exception,
    ) -> None:
        try:
            db.session.rollback()
        except Exception:
            logger.exception(
                (
                    "Failed to rollback DB session "
                    "during recovery for %s"
                ),
                session_id,
            )

        try:
            crawl_session = repository.get(
                session_id=session_id,
            )
        except Exception:
            logger.exception(
                (
                    "Failed to reload crawl session "
                    "during recovery: %s"
                ),
                session_id,
            )
            return

        if crawl_session is None:
            logger.error(
                "Cannot recover missing crawl session: %s",
                session_id,
            )
            return

        error_message = (
            str(error).strip()
            or error.__class__.__name__
        )

        try:
            repository.mark_failed(
                session=crawl_session,
                error_message=error_message[:2000],
            )
        except Exception:
            logger.exception(
                (
                    "Final crawl recovery failed "
                    "for session %s"
                ),
                session_id,
            )


# New canonical name; the legacy class remains the implementation in Phase 1A
# so existing monkeypatch-based tests keep their module seams intact.
BackgroundInstagramSyncRunner = BackgroundCrawlRunner
