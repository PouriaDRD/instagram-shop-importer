from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.crawler.instagram.dto import (
    InstagramMediaDTO,
    InstagramProfileDTO,
)
from app.extensions import db
from app.models import (
    CrawledAsset,
    CrawledMedia,
    CrawlSession,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CrawlSessionRepository:
    def create(
        self,
        *,
        username: str,
    ) -> CrawlSession:
        session = CrawlSession(
            username=username,
            status="pending",
        )

        db.session.add(session)
        db.session.commit()

        return session

    def get(
        self,
        *,
        session_id: str,
    ) -> CrawlSession | None:
        return db.session.get(
            CrawlSession,
            session_id,
        )

    def list_all(
        self,
        *,
        limit: int = 100,
    ) -> list[CrawlSession]:
        statement = (
            select(CrawlSession).order_by(CrawlSession.created_at.desc()).limit(limit)
        )

        return list(db.session.scalars(statement).all())

    def mark_running(
        self,
        *,
        session: CrawlSession,
    ) -> None:
        session.status = "running"
        session.started_at = utc_now()
        session.completed_at = None
        session.error_message = None

        db.session.commit()

    def save_profile(
        self,
        *,
        session: CrawlSession,
        profile: InstagramProfileDTO,
    ) -> None:
        session.username = profile.username
        session.full_name = profile.full_name
        session.biography = profile.biography

        session.profile_picture_url = profile.profile_picture_url

        session.followers_count = profile.followers_count

        session.following_count = profile.following_count

        session.instagram_media_count = profile.media_count

        session.is_private = profile.is_private

        db.session.commit()

    def replace_media(
        self,
        *,
        session: CrawlSession,
        media_items: tuple[
            InstagramMediaDTO,
            ...,
        ],
    ) -> None:
        session.media.clear()

        db.session.flush()

        for media_position, item in enumerate(media_items):
            media = CrawledMedia(
                session=session,
                media_id=item.media_id,
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
                raw_payload=item.raw_payload,
            )

            db.session.add(media)

            for asset in item.assets:
                crawled_asset = CrawledAsset(
                    external_id=asset.external_id,
                    asset_type=asset.asset_type.value,
                    source_url=asset.source_url,
                    position=asset.position,
                    width=asset.width,
                    height=asset.height,
                    duration_seconds=(asset.duration_seconds),
                    is_selected=True,
                    asset_metadata=asset.metadata,
                )

                media.assets.append(crawled_asset)

        session.crawled_media_count = len(media_items)

        db.session.commit()

    def mark_completed(
        self,
        *,
        session: CrawlSession,
    ) -> None:
        session.status = "completed"
        session.completed_at = utc_now()
        session.error_message = None

        db.session.commit()

    def mark_failed(
        self,
        *,
        session: CrawlSession,
        error_message: str,
    ) -> None:
        session.status = "failed"
        session.completed_at = utc_now()
        session.error_message = error_message

        db.session.commit()
