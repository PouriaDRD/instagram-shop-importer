from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from app.extensions import db

if TYPE_CHECKING:
    from app.models.instagram_source import InstagramSource


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InstagramMedia(db.Model):
    """
    Persistent Instagram media.

    Identity:
        (source_id, media_id)

    Re-crawling the same post/reel updates this row in place. A media row is
    never deleted merely because it was absent from a later crawl.
    """

    __tablename__ = "crawled_media"

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "media_id",
            name="uq_instagram_media_source_media_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    source_id: Mapped[str] = mapped_column(
        "session_id",
        String(36),
        ForeignKey(
            "crawl_sessions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    media_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    shortcode: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    media_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    permalink: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    caption: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )

    thumbnail_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    like_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    comment_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    view_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    position: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    is_selected: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    is_available: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
    )

    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    raw_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    source: Mapped["InstagramSource"] = relationship(
        "InstagramSource",
        back_populates="media",
    )

    assets: Mapped[list["InstagramAsset"]] = relationship(
        "InstagramAsset",
        back_populates="media",
        cascade="all, delete-orphan",
        order_by="InstagramAsset.position",
    )

    def __init__(
        self,
        *,
        source: "InstagramSource | None" = None,
        session: "InstagramSource | None" = None,
        media_id: str,
        shortcode: str,
        media_type: str,
        permalink: str,
        caption: str = "",
        thumbnail_url: str | None = None,
        published_at: datetime | None = None,
        like_count: int | None = None,
        comment_count: int | None = None,
        view_count: int | None = None,
        position: int = 0,
        is_selected: bool = True,
        is_available: bool = True,
        last_seen_at: datetime | None = None,
        raw_payload: dict[str, Any] | None = None,
    ) -> None:
        effective_source = source or session

        if effective_source is None:
            raise ValueError("InstagramMedia requires a source.")

        self.source = effective_source
        self.media_id = media_id
        self.shortcode = shortcode
        self.media_type = media_type
        self.permalink = permalink
        self.caption = caption
        self.thumbnail_url = thumbnail_url
        self.published_at = published_at
        self.like_count = like_count
        self.comment_count = comment_count
        self.view_count = view_count
        self.position = position
        self.is_selected = is_selected
        self.is_available = is_available
        self.last_seen_at = last_seen_at
        self.raw_payload = raw_payload if raw_payload is not None else {}

    @property
    def session_id(self) -> str:
        return self.source_id

    @property
    def session(self) -> "InstagramSource":
        return self.source

    @session.setter
    def session(
        self,
        value: "InstagramSource",
    ) -> None:
        self.source = value

    def __repr__(self) -> str:
        return (
            "<InstagramMedia "
            f"shortcode={self.shortcode!r} "
            f"type={self.media_type!r} "
            f"available={self.is_available!r}>"
        )


class InstagramAsset(db.Model):
    """
    Persistent asset belonging to one InstagramMedia.

    Identity:
        (media_id, asset_type, position)

    CDN/source URLs are mutable source data, not identity.
    """

    __tablename__ = "crawled_assets"

    __table_args__ = (
        UniqueConstraint(
            "media_id",
            "asset_type",
            "position",
            name="uq_instagram_asset_media_type_position",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    media_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "crawled_media.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    external_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
    )

    asset_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    source_url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    local_cache_path: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    local_cache_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="missing",
    )

    local_cached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    local_content_type: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    local_file_size: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    local_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    local_cache_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    position: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    width: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    height: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    duration_seconds: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    is_selected: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    is_available: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
    )

    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    asset_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )

    media: Mapped[InstagramMedia] = relationship(
        "InstagramMedia",
        back_populates="assets",
    )

    def __init__(
        self,
        *,
        external_id: str,
        asset_type: str,
        source_url: str,
        position: int = 0,
        width: int | None = None,
        height: int | None = None,
        duration_seconds: float | None = None,
        is_selected: bool = True,
        is_available: bool = True,
        last_seen_at: datetime | None = None,
        asset_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.external_id = external_id
        self.asset_type = asset_type
        self.source_url = source_url
        self.position = position
        self.width = width
        self.height = height
        self.duration_seconds = duration_seconds
        self.is_selected = is_selected
        self.is_available = is_available
        self.last_seen_at = last_seen_at
        self.asset_metadata = (
            asset_metadata
            if asset_metadata is not None
            else {}
        )

    def __repr__(self) -> str:
        return (
            "<InstagramAsset "
            f"type={self.asset_type!r} "
            f"position={self.position} "
            f"available={self.is_available!r}>"
        )


CrawledMedia = InstagramMedia
CrawledAsset = InstagramAsset
