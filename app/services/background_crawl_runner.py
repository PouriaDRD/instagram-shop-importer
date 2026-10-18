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
        thread = threading.Thread(
            target=self._run,
            kwargs=kwargs,
            name=f"crawl-{session_id}",
            daemon=True,
        )

        thread.start()

    @staticmethod
    def _run(
        *,
        app: Flask,
        session_id: str,
        max_items: int | None,
        sort_order: str = "newest",
        auth_state_path: str | None = None,
    ) -> None:
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
                service = CrawlService(
                    provider=provider,
                    repository=repository,
                )

                if sort_order == "newest":
                    service.run(session_id=session_id, max_items=max_items)
                else:
                    service.run(
                        session_id=session_id,
                        max_items=max_items,
                        sort_order=sort_order,
                    )

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
            if context_pushed:
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
