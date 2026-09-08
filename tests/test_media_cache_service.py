from __future__ import annotations

from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from app.services.media_cache_service import (
    InstagramMediaCacheService,
)


class FakeResponse:
    def __init__(
        self,
        *,
        body: bytes,
        content_type: str,
    ) -> None:
        self._body = body
        self._offset = 0
        self.headers = Message()
        self.headers["Content-Type"] = (
            content_type
        )
        self.headers["Content-Length"] = str(
            len(body)
        )

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc,
        traceback,
    ) -> None:
        return None

    def read(
        self,
        size: int,
    ) -> bytes:
        if self._offset >= len(self._body):
            return b""

        chunk = self._body[
            self._offset:
            self._offset + size
        ]
        self._offset += len(chunk)
        return chunk


def _asset() -> SimpleNamespace:
    return SimpleNamespace(
        id=str(uuid.uuid4()),
        media_id=str(uuid.uuid4()),
        asset_type="image",
        position=0,
        source_url=(
            "https://instagram.example/"
            "temporary-image.jpg"
        ),
        local_cache_path=None,
        local_cache_status="missing",
        local_cached_at=None,
        local_content_type=None,
        local_file_size=None,
        local_sha256=None,
        local_cache_error=None,
    )


def test_cache_asset_downloads_and_records_metadata(
    tmp_path: Path,
) -> None:
    service = InstagramMediaCacheService(
        root_path=str(tmp_path),
        timeout_seconds=5,
        max_bytes=1024 * 1024,
    )
    asset = _asset()
    body = b"fake-jpeg-content"

    with patch(
        "app.services.media_cache_service.urlopen",
        return_value=FakeResponse(
            body=body,
            content_type="image/jpeg",
        ),
    ):
        service._cache_asset(
            asset=asset,
            username="shop",
            shortcode="ABC123",
        )

    assert asset.local_cache_status == "ready"
    assert asset.local_cache_path
    assert asset.local_content_type == "image/jpeg"
    assert asset.local_file_size == len(body)
    assert len(asset.local_sha256) == 64

    cached_path = (
        tmp_path
        / asset.local_cache_path
    )

    assert cached_path.read_bytes() == body


def test_existing_cache_is_reused_even_if_source_url_changes(
    tmp_path: Path,
) -> None:
    service = InstagramMediaCacheService(
        root_path=str(tmp_path),
        timeout_seconds=5,
        max_bytes=1024 * 1024,
    )
    asset = _asset()

    existing = (
        tmp_path
        / "shop"
        / "ABC123"
        / "existing.jpg"
    )
    existing.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    existing.write_bytes(
        b"existing-cache"
    )

    asset.local_cache_path = (
        existing.relative_to(
            tmp_path
        ).as_posix()
    )
    asset.source_url = (
        "https://instagram.example/"
        "rotated-cdn-url.jpg"
    )

    assert service._has_valid_cache(
        asset=asset
    )
