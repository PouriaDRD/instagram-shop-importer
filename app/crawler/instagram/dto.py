from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


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


def _validate_http_url(
    value: str | None,
) -> str | None:
    """
    Validate that a URL is HTTP or HTTPS.

    The DTO intentionally exposes URLs as plain strings rather than
    Pydantic HttpUrl objects. This keeps the domain/provider boundary
    simple and fully compatible with static type checkers such as
    Pylance and mypy.
    """

    if value is None:
        return None

    normalized = value.strip()

    if not normalized:
        return None

    if not normalized.startswith(
        (
            "http://",
            "https://",
        )
    ):
        raise ValueError("URL must start with http:// or https://")

    return normalized


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

    profile_picture_url: str | None = None

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

    @field_validator(
        "profile_picture_url",
    )
    @classmethod
    def validate_profile_picture_url(
        cls,
        value: str | None,
    ) -> str | None:
        return _validate_http_url(value)


class InstagramAssetDTO(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    external_id: str = ""

    asset_type: InstagramAssetType

    source_url: str

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

    @field_validator(
        "source_url",
    )
    @classmethod
    def validate_source_url(
        cls,
        value: str,
    ) -> str:
        validated = _validate_http_url(value)

        if validated is None:
            raise ValueError("source_url cannot be empty")

        return validated


class InstagramMediaDTO(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    media_id: str = Field(
        min_length=1,
    )

    shortcode: str = Field(
        min_length=1,
    )

    media_type: InstagramMediaType

    permalink: str

    caption: str = ""

    thumbnail_url: str | None = None

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

    @field_validator(
        "permalink",
    )
    @classmethod
    def validate_permalink(
        cls,
        value: str,
    ) -> str:
        validated = _validate_http_url(value)

        if validated is None:
            raise ValueError("permalink cannot be empty")

        return validated

    @field_validator(
        "thumbnail_url",
    )
    @classmethod
    def validate_thumbnail_url(
        cls,
        value: str | None,
    ) -> str | None:
        return _validate_http_url(value)
