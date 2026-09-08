from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.crawler.instagram.dto import (
    InstagramMediaDTO,
    InstagramProfileDTO,
)
from app.extensions import db
from app.models import (
    InstagramAsset,
    InstagramMedia,
    InstagramSource,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_username(value: str) -> str:
    return value.strip().lstrip("@").strip().lower()


@dataclass(frozen=True, slots=True)
class InstagramMediaSyncResult:
    created_media: int
    updated_media: int
    unavailable_media: int
    created_assets: int
    updated_assets: int
    unavailable_assets: int


class InstagramSourceRepository:
    def get_or_create(
        self,
        *,
        username: str,
    ) -> tuple[InstagramSource, bool]:
        normalized_username = normalize_username(username)

        if not normalized_username:
            raise ValueError("Instagram username is required.")

        existing = db.session.scalar(
            select(InstagramSource)
            .where(
                InstagramSource.username
                == normalized_username
            )
            .limit(1)
        )

        if existing is not None:
            return existing, False

        source = InstagramSource(
            username=normalized_username,
            status="pending",
        )

        db.session.add(source)

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()

            existing = db.session.scalar(
                select(InstagramSource)
                .where(
                    InstagramSource.username
                    == normalized_username
                )
                .limit(1)
            )

            if existing is None:
                raise

            return existing, False

        return source, True

    def create(
        self,
        *,
        username: str,
    ) -> InstagramSource:
        source, _created = self.get_or_create(
            username=username,
        )
        return source

    def get(
        self,
        *,
        source_id: str | None = None,
        session_id: str | None = None,
    ) -> InstagramSource | None:
        effective_id = source_id or session_id

        if not effective_id:
            return None

        return db.session.get(
            InstagramSource,
            effective_id,
        )

    def list_all(
        self,
        *,
        limit: int = 100,
    ) -> list[InstagramSource]:
        statement = (
            select(InstagramSource)
            .order_by(
                InstagramSource.created_at.desc()
            )
            .limit(limit)
        )

        return list(
            db.session.scalars(statement).all()
        )

    def mark_running(
        self,
        *,
        source: InstagramSource | None = None,
        session: InstagramSource | None = None,
    ) -> None:
        target = source or session

        if target is None:
            raise ValueError("Instagram source is required.")

        target.status = "running"
        target.started_at = utc_now()
        target.completed_at = None
        target.error_message = None

        db.session.commit()

    def save_profile(
        self,
        *,
        source: InstagramSource | None = None,
        session: InstagramSource | None = None,
        profile: InstagramProfileDTO,
    ) -> None:
        target = source or session

        if target is None:
            raise ValueError("Instagram source is required.")

        target.username = normalize_username(
            profile.username
        )
        target.full_name = profile.full_name
        target.biography = profile.biography
        target.profile_picture_url = (
            profile.profile_picture_url
        )
        target.followers_count = (
            profile.followers_count
        )
        target.following_count = (
            profile.following_count
        )
        target.instagram_media_count = (
            profile.media_count
        )
        target.is_private = profile.is_private

        db.session.commit()

    def sync_media(
        self,
        *,
        source: InstagramSource | None = None,
        session: InstagramSource | None = None,
        media_items: tuple[InstagramMediaDTO, ...],
        full_sync: bool,
    ) -> InstagramMediaSyncResult:
        """
        Non-destructive source synchronization.

        Rules:
        - media identity is (source, provider media_id)
        - asset identity is (media, asset_type, position)
        - existing rows are updated in place
        - missing media is marked unavailable only after a FULL source crawl
        - missing assets for a fetched media are marked unavailable
        - nothing is hard-deleted
        """

        target = source or session

        if target is None:
            raise ValueError("Instagram source is required.")

        now = utc_now()

        existing_media = {
            media.media_id: media
            for media in db.session.scalars(
                select(InstagramMedia)
                .where(
                    InstagramMedia.source_id
                    == target.id
                )
            ).all()
        }

        seen_media_ids: set[str] = set()

        created_media = 0
        updated_media = 0
        unavailable_media = 0
        created_assets = 0
        updated_assets = 0
        unavailable_assets = 0

        for media_position, item in enumerate(
            media_items
        ):
            provider_media_id = str(
                item.media_id or ""
            ).strip()

            if not provider_media_id:
                raise ValueError(
                    "Instagram media_id is required."
                )

            if provider_media_id in seen_media_ids:
                raise ValueError(
                    (
                        "Duplicate Instagram media_id "
                        f"in one sync payload: {provider_media_id}"
                    )
                )

            seen_media_ids.add(
                provider_media_id
            )

            media = existing_media.get(
                provider_media_id
            )

            if media is None:
                media = InstagramMedia(
                    source=target,
                    media_id=provider_media_id,
                    shortcode=item.shortcode,
                    media_type=item.media_type.value,
                    permalink=item.permalink,
                    caption=item.caption,
                    thumbnail_url=item.thumbnail_url,
                    published_at=item.published_at,
                    like_count=item.like_count,
                    comment_count=item.comment_count,
                    view_count=item.view_count,
                    position=media_position,
                    is_selected=True,
                    is_available=True,
                    last_seen_at=now,
                    raw_payload=item.raw_payload,
                )

                db.session.add(media)
                db.session.flush()

                existing_media[
                    provider_media_id
                ] = media
                created_media += 1

            else:
                self._update_media(
                    media=media,
                    item=item,
                    position=media_position,
                    seen_at=now,
                )
                updated_media += 1

            asset_result = self._sync_assets(
                media=media,
                assets=item.assets,
                seen_at=now,
            )

            created_assets += (
                asset_result[0]
            )
            updated_assets += (
                asset_result[1]
            )
            unavailable_assets += (
                asset_result[2]
            )

        if full_sync:
            for media_id, media in (
                existing_media.items()
            ):
                if media_id in seen_media_ids:
                    continue

                if media.is_available:
                    media.is_available = False
                    unavailable_media += 1

        target.crawled_media_count = len(
            media_items
        )

        db.session.commit()

        return InstagramMediaSyncResult(
            created_media=created_media,
            updated_media=updated_media,
            unavailable_media=unavailable_media,
            created_assets=created_assets,
            updated_assets=updated_assets,
            unavailable_assets=unavailable_assets,
        )

    def replace_media(
        self,
        *,
        source: InstagramSource | None = None,
        session: InstagramSource | None = None,
        media_items: tuple[InstagramMediaDTO, ...],
    ) -> None:
        """
        Legacy compatibility seam.

        Old callers did not tell us whether the crawl covered the full account.
        Therefore this compatibility method performs a safe partial sync and
        never marks unseen media unavailable.
        """

        self.sync_media(
            source=source,
            session=session,
            media_items=media_items,
            full_sync=False,
        )

    @staticmethod
    def _update_media(
        *,
        media: InstagramMedia,
        item: InstagramMediaDTO,
        position: int,
        seen_at: datetime,
    ) -> None:
        media.shortcode = item.shortcode
        media.media_type = item.media_type.value
        media.permalink = item.permalink
        media.caption = item.caption
        media.thumbnail_url = item.thumbnail_url
        media.published_at = item.published_at
        media.like_count = item.like_count
        media.comment_count = item.comment_count
        media.view_count = item.view_count
        media.position = position
        media.raw_payload = item.raw_payload
        media.is_available = True
        media.last_seen_at = seen_at

    @staticmethod
    def _sync_assets(
        *,
        media: InstagramMedia,
        assets,
        seen_at: datetime,
    ) -> tuple[int, int, int]:
        existing_assets = {
            (
                asset.asset_type,
                asset.position,
            ): asset
            for asset in db.session.scalars(
                select(InstagramAsset)
                .where(
                    InstagramAsset.media_id
                    == media.id
                )
            ).all()
        }

        seen_keys: set[
            tuple[str, int]
        ] = set()

        created = 0
        updated = 0
        unavailable = 0

        for item in assets:
            key = (
                item.asset_type.value,
                int(item.position),
            )

            if key in seen_keys:
                raise ValueError(
                    (
                        "Duplicate Instagram asset identity "
                        f"in one media payload: {key!r}"
                    )
                )

            seen_keys.add(key)

            asset = existing_assets.get(
                key
            )

            if asset is None:
                asset = InstagramAsset(
                    external_id=item.external_id,
                    asset_type=item.asset_type.value,
                    source_url=item.source_url,
                    position=item.position,
                    width=item.width,
                    height=item.height,
                    duration_seconds=(
                        item.duration_seconds
                    ),
                    is_selected=True,
                    is_available=True,
                    last_seen_at=seen_at,
                    asset_metadata=item.metadata,
                )

                media.assets.append(asset)
                db.session.flush()

                existing_assets[key] = asset
                created += 1
                continue

            asset.external_id = item.external_id
            asset.source_url = item.source_url
            asset.width = item.width
            asset.height = item.height
            asset.duration_seconds = (
                item.duration_seconds
            )
            asset.asset_metadata = (
                item.metadata
            )
            asset.is_available = True
            asset.last_seen_at = seen_at

            updated += 1

        for key, asset in (
            existing_assets.items()
        ):
            if key in seen_keys:
                continue

            if asset.is_available:
                asset.is_available = False
                unavailable += 1

        return (
            created,
            updated,
            unavailable,
        )

    def mark_completed(
        self,
        *,
        source: InstagramSource | None = None,
        session: InstagramSource | None = None,
    ) -> None:
        target = source or session

        if target is None:
            raise ValueError("Instagram source is required.")

        target.status = "completed"
        target.completed_at = utc_now()
        target.error_message = None

        db.session.commit()

    def mark_failed(
        self,
        *,
        source: InstagramSource | None = None,
        session: InstagramSource | None = None,
        error_message: str,
    ) -> None:
        target = source or session

        if target is None:
            raise ValueError("Instagram source is required.")

        target.status = "failed"
        target.completed_at = utc_now()
        target.error_message = error_message

        db.session.commit()
