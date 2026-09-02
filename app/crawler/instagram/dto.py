from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class InstagramMediaType(StrEnum):
    IMAGE = "image"
    CAROUSEL = "carousel"
    REEL = "reel"
    VIDEO = "video"
    UNKNOWN = "unknown"


class InstagramAssetType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    THUMBNAIL = "thumbnail"


class InstagramProfileDTO(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    username: str = Field(
        min_length=1,
        max_length=255,
    )

    full_name: str = ""
    biography: str = ""

    profile_picture_url: HttpUrl | None = None

    followers_count: int | None = Field(
        default=None,
        ge=0,
    )

    following_count: int | None = Field(
        default=None,
        ge=0,
    )

    media_count: int | None = Field(
        default=None,
        ge=0,
    )

    is_private: bool | None = None

    raw_payload: dict[str, Any] = Field(
        default_factory=dict,
    )


class InstagramAssetDTO(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    external_id: str

    asset_type: InstagramAssetType

    source_url: HttpUrl

    position: int = Field(
        ge=0,
    )

    width: int | None = Field(
        default=None,
        ge=0,
    )

    height: int | None = Field(
        default=None,
        ge=0,
    )

    duration_seconds: float | None = Field(
        default=None,
        ge=0,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )


class InstagramMediaDTO(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    media_id: str
    shortcode: str

    media_type: InstagramMediaType

    permalink: HttpUrl

    caption: str = ""

    thumbnail_url: HttpUrl | None = None

    published_at: datetime | None = None

    like_count: int | None = Field(
        default=None,
        ge=0,
    )

    comment_count: int | None = Field(
        default=None,
        ge=0,
    )

    view_count: int | None = Field(
        default=None,
        ge=0,
    )

    assets: tuple[
        InstagramAssetDTO,
        ...,
    ] = ()

    raw_payload: dict[str, Any] = Field(
        default_factory=dict,
    )
