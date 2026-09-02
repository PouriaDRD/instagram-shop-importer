from __future__ import annotations

from typing import Protocol

from app.crawler.instagram.dto import (
    InstagramMediaDTO,
    InstagramProfileDTO,
)


class InstagramProvider(Protocol):
    def fetch_profile(
        self,
        *,
        username: str,
    ) -> InstagramProfileDTO: ...

    def fetch_media(
        self,
        *,
        username: str,
        max_items: int | None = None,
    ) -> tuple[
        InstagramMediaDTO,
        ...,
    ]: ...
