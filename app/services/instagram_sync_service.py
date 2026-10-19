from __future__ import annotations

import logging
from collections.abc import Callable

from flask import has_app_context

from app.services.crawl_job_progress import CrawlCancelled
from app.config import Config
from app.crawler.base import InstagramProvider
from app.models import InstagramSource
from app.repositories import InstagramSourceRepository
from app.services.media_storage_service import (
    InstagramMediaStorageService,
)

logger = logging.getLogger("crawler")


class InstagramSyncService:
    """
    Persistent Instagram source synchronization.

    The concrete InstagramSourceRepository uses non-destructive sync_media().
    Legacy/fake repositories used by the existing test suite continue through
    replace_media() until their contracts are migrated in a later cleanup
    phase.
    """

    def __init__(
        self,
        *,
        provider: InstagramProvider,
        repository: InstagramSourceRepository,
        media_storage_service: (
            InstagramMediaStorageService | None
        ) = None,
    ) -> None:
        self._provider = provider
        self._repository = repository
        self._media_storage_service = (
            media_storage_service
        )

    def get_or_create_source(
        self,
        *,
        username: str,
    ) -> InstagramSource:
        normalized_username = (
            username.strip()
            .lstrip("@")
            .strip()
            .lower()
        )

        if not normalized_username:
            raise ValueError(
                "Instagram username is required."
            )

        return self._repository.create(
            username=normalized_username,
        )

    def create_session(
        self,
        *,
        username: str,
    ) -> InstagramSource:
        return self.get_or_create_source(
            username=username,
        )

    def run(
        self,
        *,
        source_id: str | None = None,
        session_id: str | None = None,
        max_items: int | None = None,
        sort_order: str = "newest",
        check_cancel: Callable[[], None] | None = None,
        on_progress: Callable[..., None] | None = None,
        on_audit: Callable[[dict[str, int]], None] | None = None,
    ) -> None:
        if sort_order not in {"newest", "oldest"}:
            raise ValueError("Unsupported Instagram media sort order.")

        effective_id = source_id or session_id

        if not effective_id:
            raise ValueError(
                "Instagram source id is required."
            )

        source = self._repository.get(
            session_id=effective_id,
        )

        if source is None:
            raise ValueError(
                (
                    "Crawl session does not exist: "
                    f"{effective_id}"
                )
            )

        username = source.username

        logger.info(
            "Instagram sync starting for @%s",
            username,
        )

        try:
            if check_cancel:
                check_cancel()
            self._repository.mark_running(
                session=source,
            )

            profile = (
                self._provider.fetch_profile(
                    username=username,
                )
            )

            if check_cancel:
                check_cancel()
            self._repository.save_profile(
                session=source,
                profile=profile,
            )

            if sort_order == "oldest":
                # Only the concrete provider's oldest mode requires a complete
                # pagination history. Keep the old provider protocol compatible.
                media_items = self._provider.fetch_media(
                    username=username,
                    max_items=max_items,
                    sort_order="oldest",
                    expected_media_count=profile.media_count,
                )
            else:
                media_items = self._provider.fetch_media(
                    username=username,
                    max_items=max_items,
                )

            if on_audit:
                on_audit(getattr(self._provider, "discovery_metrics", {}) or {
                    "discovered_candidates": len(media_items),
                    "detail_attempted": len(media_items),
                    "detail_succeeded": len(media_items),
                    "unique_valid": len(media_items),
                    "selected_posts": len(media_items),
                })
            if check_cancel:
                check_cancel()
            sync_result = self._persist_media(
                source=source,
                media_items=media_items,
                # Instagram does not prove exhaustiveness when its grid stops.
                # Never mark previously captured posts unavailable merely
                # because anonymous/session pagination returned fewer tiles.
                full_sync=False,
            )

            if on_audit:
                metrics = {"synced_posts": len(media_items)}
                if sync_result is not None:
                    metrics.update({"created_posts": sync_result.created_media,
                                    "updated_posts": sync_result.updated_media})
                on_audit(metrics)
            if on_progress:
                on_progress("metadata_saved", len(media_items), len(media_items))
            if check_cancel:
                check_cancel()
            self._persist_media_files_safely(
                source=source,
                media_items=media_items,
                check_cancel=check_cancel,
                on_progress=on_progress,
                on_audit=on_audit,
            )
            if check_cancel:
                check_cancel()

            self._repository.mark_completed(
                session=source,
            )

        except CrawlCancelled:
            if on_audit:
                on_audit(getattr(self._provider, "discovery_metrics", {}) or {})
            logger.info("Instagram crawl cancelled by operator for @%s", username)
            # In production the worker owns an app context. Pure service
            # unit-tests can inject a repository without one; do not attempt
            # to access Flask's context-scoped SQLAlchemy session then.
            if has_app_context():
                from app.extensions import db
                db.session.rollback()
            self._repository.mark_cancelled(session=source)
            return

        except Exception as exc:
            if on_audit:
                on_audit(getattr(self._provider, "discovery_metrics", {}) or {})
            logger.exception(
                "Instagram sync failed for @%s",
                username,
            )

            self._mark_failed_safely(
                source=source,
                error=exc,
            )
            return

        logger.info(
            (
                "Instagram sync completed "
                "for @%s: %s media"
            ),
            username,
            source.crawled_media_count,
        )

    def _persist_media(
        self,
        *,
        source: InstagramSource,
        media_items,
        full_sync: bool,
    ):
        """
        Compatibility boundary.
        """

        if (
            type(self._repository)
            is InstagramSourceRepository
        ):
            return self._repository.sync_media(
                session=source,
                media_items=media_items,
                full_sync=full_sync,
            )

        self._repository.replace_media(
            session=source,
            media_items=media_items,
        )
        return None

    def _persist_media_files_safely(
        self,
        *,
        source: InstagramSource,
        media_items=(),
        check_cancel: Callable[[], None] | None = None,
        on_progress: Callable[..., None] | None = None,
        on_audit: Callable[[dict[str, int]], None] | None = None,
    ) -> None:
        if not Config.INSTAGRAM_MEDIA_STORAGE_ENABLED:
            return

        # Existing fake/subclass repository tests retain their historical
        # seam and must never start doing real network I/O.
        if (
            type(self._repository)
            is not InstagramSourceRepository
            and self._media_storage_service
            is None
        ):
            return

        service = (
            self._media_storage_service
            or InstagramMediaStorageService(
                root_path=(
                    Config.INSTAGRAM_MEDIA_STORAGE_DIR
                ),
                timeout_seconds=(
                    Config
                    .INSTAGRAM_MEDIA_STORAGE_TIMEOUT_SECONDS
                ),
                max_bytes=(
                    Config.INSTAGRAM_MEDIA_STORAGE_MAX_BYTES
                ),
            )
        )

        try:
            kwargs = {"source": source}
            if type(self._repository) is InstagramSourceRepository:
                # Only this run's selected posts: do not revisit every asset
                # accumulated by previous crawls of the same Instagram page.
                from sqlalchemy import select
                from app.extensions import db
                from app.models import InstagramAsset, InstagramMedia

                selected_ids = {str(item.media_id) for item in media_items}
                selected_assets = tuple(
                    db.session.scalars(
                        select(InstagramAsset)
                        .join(InstagramMedia, InstagramAsset.media_id == InstagramMedia.id)
                        .where(
                            InstagramMedia.source_id == source.id,
                            InstagramMedia.media_id.in_(selected_ids),
                            InstagramAsset.is_available.is_(True),
                        )
                        .order_by(InstagramMedia.position, InstagramAsset.position)
                    ).all()
                ) if selected_ids else ()
                kwargs["assets"] = selected_assets
                kwargs["parallel_downloads"] = True
            if check_cancel:
                kwargs["check_cancel"] = check_cancel
            if on_progress:
                kwargs["on_progress"] = on_progress
            result = service.persist_source(**kwargs)

        except CrawlCancelled:
            raise
        except Exception:
            if on_audit:
                on_audit({"download_error": 1})
            # Local cache is deliberately auxiliary. A cache failure must not
            # turn a successful Instagram source synchronization into a failed
            # crawl.
            logger.exception(
                (
                    "Persistent local Instagram media storage "
                    "failed for @%s"
                ),
                source.username,
            )
            return

        if on_audit:
            on_audit({"download_total": result.saved + result.reused + result.failed,
                      "download_saved": result.saved, "download_reused": result.reused,
                      "download_failed": result.failed,
                      "bytes_downloaded": result.bytes_saved})
        logger.info(
            (
                "Persistent local Instagram media storage for @%s: "
                "%s cached, %s reused, %s failed"
            ),
            source.username,
            result.saved,
            result.reused,
            result.failed,
        )

    def _mark_failed_safely(
        self,
        *,
        source: InstagramSource,
        error: Exception,
    ) -> None:
        error_message = (
            self._safe_error_message(error)
        )

        try:
            if has_app_context():
                # A partially flushed media upsert must not be committed by
                # mark_failed. Keep the last successful persisted crawl intact.
                from app.extensions import db
                db.session.rollback()
            self._repository.mark_failed(
                session=source,
                error_message=error_message,
            )

        except Exception:
            logger.exception(
                (
                    "Failed to persist failed "
                    "Instagram sync state for source %s"
                ),
                source.id,
            )

    @staticmethod
    def _safe_error_message(
        error: Exception,
    ) -> str:
        message = str(error).strip()

        if message:
            return message[:2000]

        return error.__class__.__name__
