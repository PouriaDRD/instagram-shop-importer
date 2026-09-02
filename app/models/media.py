from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app import db


def utcnow():
    return datetime.now(timezone.utc)


class CrawledMedia(db.Model):
    __tablename__ = "crawled_media"

    id = db.Column(
        db.String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    session_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "crawl_sessions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    media_id = db.Column(
        db.String(255),
        nullable=False,
        default="",
    )

    shortcode = db.Column(
        db.String(255),
        nullable=False,
        index=True,
    )

    media_type = db.Column(
        db.String(32),
        nullable=False,
        default="unknown",
    )

    permalink = db.Column(
        db.Text,
        nullable=False,
    )

    caption = db.Column(
        db.Text,
        nullable=False,
        default="",
    )

    thumbnail_url = db.Column(
        db.Text,
        nullable=False,
        default="",
    )

    published_at = db.Column(
        db.DateTime(timezone=True),
        nullable=True,
    )

    like_count = db.Column(
        db.Integer,
        nullable=True,
    )

    comment_count = db.Column(
        db.Integer,
        nullable=True,
    )

    view_count = db.Column(
        db.Integer,
        nullable=True,
    )

    position = db.Column(
        db.Integer,
        nullable=False,
        default=0,
    )

    is_selected = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )

    session = db.relationship(
        "CrawlSession",
        back_populates="media",
    )

    assets = db.relationship(
        "CrawledAsset",
        back_populates="media",
        cascade="all, delete-orphan",
        order_by="CrawledAsset.position",
    )

    __table_args__ = (
        db.UniqueConstraint(
            "session_id",
            "shortcode",
            name="uq_session_shortcode",
        ),
    )


class CrawledAsset(db.Model):
    __tablename__ = "crawled_assets"

    id = db.Column(
        db.String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    media_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "crawled_media.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    external_id = db.Column(
        db.String(255),
        nullable=False,
        default="",
    )

    asset_type = db.Column(
        db.String(32),
        nullable=False,
    )

    source_url = db.Column(
        db.Text,
        nullable=False,
    )

    position = db.Column(
        db.Integer,
        nullable=False,
        default=0,
    )

    width = db.Column(
        db.Integer,
        nullable=True,
    )

    height = db.Column(
        db.Integer,
        nullable=True,
    )

    duration_seconds = db.Column(
        db.Float,
        nullable=True,
    )

    is_selected = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
    )

    media = db.relationship(
        "CrawledMedia",
        back_populates="assets",
    )
