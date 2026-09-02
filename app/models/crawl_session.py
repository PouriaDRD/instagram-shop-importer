from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app import db


def utcnow():
    return datetime.now(timezone.utc)


class CrawlSession(db.Model):
    __tablename__ = "crawl_sessions"

    id = db.Column(
        db.String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    instagram_username = db.Column(
        db.String(255),
        nullable=False,
        index=True,
    )

    profile_name = db.Column(
        db.String(255),
        nullable=False,
        default="",
    )

    biography = db.Column(
        db.Text,
        nullable=False,
        default="",
    )

    profile_picture_url = db.Column(
        db.Text,
        nullable=False,
        default="",
    )

    followers_count = db.Column(
        db.Integer,
        nullable=True,
    )

    following_count = db.Column(
        db.Integer,
        nullable=True,
    )

    media_count = db.Column(
        db.Integer,
        nullable=True,
    )

    status = db.Column(
        db.String(32),
        nullable=False,
        default="pending",
        index=True,
    )

    error_message = db.Column(
        db.Text,
        nullable=False,
        default="",
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )

    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    media = db.relationship(
        "CrawledMedia",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="CrawledMedia.position",
    )

    def __repr__(self):
        return f"<CrawlSession " f"@{self.instagram_username}>"
