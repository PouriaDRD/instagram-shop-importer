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
    ) -> None:
        thread = threading.Thread(
            target=self._run,
            kwargs={
                "app": app,
                "session_id": session_id,
                "max_items": max_items,
            },
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
    ) -> None:
        """
        Run one crawl inside an isolated Flask application context.

        Flask-SQLAlchemy automatically removes its scoped session when
        the application context is popped.

        We intentionally do NOT call db.session.remove() manually here,
        because doing so would remove the same session twice.

        The context is pushed/popped manually instead of using:

            with app.app_context():

        so that even a teardown failure can be logged and prevented from
        escaping the background thread.
        """

        app_context = app.app_context()
        context_pushed = False

        try:
            app_context.push()
            context_pushed = True

            repository = CrawlSessionRepository()

            try:
                service = CrawlService(
                    provider=(PlaywrightInstagramProvider()),
                    repository=repository,
                )

                service.run(
                    session_id=session_id,
                    max_items=max_items,
                )

            except Exception as exc:
                logger.exception(
                    ("Unexpected background " "crawl failure: %s"),
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
                        ("Failed to tear down application " "context after crawl %s"),
                        session_id,
                    )

    @staticmethod
    def _recover_failed_session(
        *,
        repository: CrawlSessionRepository,
        session_id: str,
        error: Exception,
    ) -> None:
        """
        Last-resort recovery layer.

        If the normal CrawlService failure handling itself crashes,
        rollback the SQLAlchemy transaction and make one final attempt
        to persist a failed state.
        """

        try:
            db.session.rollback()

        except Exception:
            logger.exception(
                ("Failed to rollback DB session " "during recovery for %s"),
                session_id,
            )

        try:
            crawl_session = repository.get(
                session_id=session_id,
            )

        except Exception:
            logger.exception(
                ("Failed to reload crawl session " "during recovery: %s"),
                session_id,
            )
            return

        if crawl_session is None:
            logger.error(
                ("Cannot recover missing crawl " "session: %s"),
                session_id,
            )
            return

        error_message = str(error).strip() or error.__class__.__name__

        try:
            repository.mark_failed(
                session=crawl_session,
                error_message=error_message[:2000],
            )

        except Exception:
            logger.exception(
                ("Final crawl recovery failed " "for session %s"),
                session_id,
            )
