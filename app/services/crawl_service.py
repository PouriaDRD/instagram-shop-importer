from __future__ import annotations

import logging

from app.crawler.base import InstagramProvider
from app.models import CrawlSession
from app.repositories import CrawlSessionRepository

logger = logging.getLogger("crawler")


class CrawlService:
    def __init__(
        self,
        *,
        provider: InstagramProvider,
        repository: CrawlSessionRepository,
    ) -> None:
        self._provider = provider
        self._repository = repository

    def create_session(
        self,
        *,
        username: str,
    ) -> CrawlSession:
        normalized_username = username.strip().lstrip("@").strip()

        if not normalized_username:
            raise ValueError("Instagram username is required.")

        return self._repository.create(
            username=normalized_username,
        )

    def run(
        self,
        *,
        session_id: str,
        max_items: int | None = None,
    ) -> None:
        session = self._repository.get(
            session_id=session_id,
        )

        if session is None:
            raise ValueError(("Crawl session does not exist: " f"{session_id}"))

        username = session.username

        logger.info(
            "Crawl starting for @%s",
            username,
        )

        try:
            self._repository.mark_running(
                session=session,
            )

            logger.info(
                "Crawl started for @%s",
                username,
            )

            profile = self._provider.fetch_profile(
                username=username,
            )

            self._repository.save_profile(
                session=session,
                profile=profile,
            )

            media_items = self._provider.fetch_media(
                username=username,
                max_items=max_items,
            )

            self._repository.replace_media(
                session=session,
                media_items=media_items,
            )

            self._repository.mark_completed(
                session=session,
            )

        except Exception as exc:
            logger.exception(
                "Crawl failed for @%s",
                username,
            )

            self._mark_failed_safely(
                session=session,
                error=exc,
            )

            return

        logger.info(
            "Crawl completed for @%s: %s media",
            username,
            session.crawled_media_count,
        )

    def _mark_failed_safely(
        self,
        *,
        session: CrawlSession,
        error: Exception,
    ) -> None:
        error_message = self._safe_error_message(
            error,
        )

        try:
            self._repository.mark_failed(
                session=session,
                error_message=error_message,
            )

        except Exception:
            logger.exception(
                ("Failed to persist failed " "crawl state for session %s"),
                session.id,
            )

    @staticmethod
    def _safe_error_message(
        error: Exception,
    ) -> str:
        message = str(error).strip()

        if message:
            return message[:2000]

        return error.__class__.__name__
