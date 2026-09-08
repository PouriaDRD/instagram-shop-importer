from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

if TYPE_CHECKING:
    from app.models.media import InstagramMedia


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InstagramSource(db.Model):
    """
    Persistent local representation of one Instagram account.

    Repeated syncs of the same normalized Instagram username must reuse this
    row. Phase 1B enforces that invariant at the database boundary.
    """

    __tablename__ = "crawl_sessions"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    username: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        index=True,
    )

    full_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
    )

    biography: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )

    profile_picture_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    followers_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    following_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    instagram_media_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    crawled_media_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    is_private: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    media: Mapped[list["InstagramMedia"]] = relationship(
        "InstagramMedia",
        back_populates="source",
        cascade="all, delete-orphan",
        order_by="InstagramMedia.position",
    )

    def __init__(
        self,
        *,
        username: str,
        status: str = "pending",
    ) -> None:
        self.username = username
        self.status = status

    def __repr__(self) -> str:
        return (
            "<InstagramSource "
            f"id={self.id!r} "
            f"username={self.username!r} "
            f"status={self.status!r}>"
        )
