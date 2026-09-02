from __future__ import annotations

from enum import Enum
from typing import Any
from datetime import datetime
from dataclasses import dataclass, field


class InstagramMediaType(str, Enum):
    IMAGE = "image"
    CAROUSEL = "carousel"
    REEL = "reel"
    VIDEO = "video"
    UNKNOWN = "unknown"


class InstagramAssetType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    THUMBNAIL = "thumbnail"


@dataclass(slots=True)
class InstagramProfileDTO:
    username: str

    full_name: str = ""
    biography: str = ""

    profile_picture_url: str = ""

    followers_count: int | None = None
    following_count: int | None = None
    media_count: int | None = None

    is_private: bool | None = None

    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class InstagramAssetDTO:
    asset_type: InstagramAssetType
    source_url: str
    position: int

    external_id: str = ""

    width: int | None = None
    height: int | None = None

    duration_seconds: float | None = None

    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class InstagramMediaDTO:
    media_id: str
    shortcode: str
    media_type: InstagramMediaType

    permalink: str

    caption: str = ""
    thumbnail_url: str = ""

    published_at: datetime | None = None

    like_count: int | None = None
    comment_count: int | None = None
    view_count: int | None = None

    assets: tuple[
        InstagramAssetDTO,
        ...,
    ] = ()

    raw_payload: dict[str, Any] = field(default_factory=dict)
