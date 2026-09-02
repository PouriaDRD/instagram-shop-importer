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
        with app.app_context():
            try:
                service = CrawlService(
                    provider=(PlaywrightInstagramProvider()),
                    repository=(CrawlSessionRepository()),
                )

                service.run(
                    session_id=session_id,
                    max_items=max_items,
                )

            except Exception:
                logger.exception(
                    ("Unexpected background " "crawl failure: %s"),
                    session_id,
                )

            finally:
                db.session.remove()
