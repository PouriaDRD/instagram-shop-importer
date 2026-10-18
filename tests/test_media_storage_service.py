from __future__ import annotations

from email.message import Message
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from app.services.media_storage_service import (
    InstagramMediaStorageService,
    _AssetSnapshot,
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
        local_file_path=None,
        local_file_status="missing",
        local_saved_at=None,
        local_content_type=None,
        local_file_size=None,
        local_sha256=None,
        local_file_error=None,
    )


def _snapshot(asset: SimpleNamespace, *, shortcode: str = "ABC123") -> _AssetSnapshot:
    """Build the immutable input used by the SQLite-lock-safe storage path."""
    return _AssetSnapshot(
        asset_id=asset.id,
        source_url=asset.source_url,
        media_id=asset.media_id,
        shortcode=shortcode,
        asset_type=asset.asset_type,
        position=asset.position,
        local_file_path=asset.local_file_path,
        local_file_status=asset.local_file_status,
        local_file_error=asset.local_file_error,
    )


def test_persist_snapshot_downloads_and_records_metadata(
    tmp_path: Path,
) -> None:
    service = InstagramMediaStorageService(
        root_path=str(tmp_path),
        timeout_seconds=5,
        max_bytes=1024 * 1024,
    )
    asset = _asset()
    body = b"fake-jpeg-content"

    with patch(
        "app.services.media_storage_service.urlopen",
        return_value=FakeResponse(
            body=body,
            content_type="image/jpeg",
        ),
    ):
        result = service._persist_snapshot(
            snapshot=_snapshot(asset),
            username="shop",
        )

    assert result.content_type == "image/jpeg"
    assert result.size_bytes == len(body)
    assert result.sha256 == hashlib.sha256(body).hexdigest()
    assert result.saved_at.tzinfo is not None
    assert result.relative_path.startswith("shop/ABC123/")
    assert (tmp_path / result.relative_path).read_bytes() == body
    assert not (tmp_path / (result.relative_path + ".part")).exists()


def test_existing_storage_is_reused_even_if_source_url_changes(
    tmp_path: Path,
) -> None:
    service = InstagramMediaStorageService(
        root_path=str(tmp_path),
        timeout_seconds=5,
        max_bytes=1024 * 1024,
    )
    asset = _asset()

    existing = tmp_path / "shop" / "ABC123" / "existing.jpg"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_bytes(b"existing-storage")

    asset.local_file_path = existing.relative_to(tmp_path).as_posix()
    asset.source_url = "https://instagram.example/rotated-cdn-url.jpg"

    assert service._snapshot_has_persisted_file(snapshot=_snapshot(asset))


def test_missing_or_empty_local_file_is_not_reused(tmp_path: Path) -> None:
    service = InstagramMediaStorageService(
        root_path=str(tmp_path), timeout_seconds=5, max_bytes=1024 * 1024
    )
    asset = _asset()
    asset.local_file_path = "shop/ABC123/empty.jpg"
    assert not service._snapshot_has_persisted_file(snapshot=_snapshot(asset))

    destination = tmp_path / asset.local_file_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"")
    assert not service._snapshot_has_persisted_file(snapshot=_snapshot(asset))


def test_storage_rejects_paths_outside_root(tmp_path: Path) -> None:
    service = InstagramMediaStorageService(
        root_path=str(tmp_path), timeout_seconds=5, max_bytes=1024 * 1024
    )
    asset = _asset()
    asset.local_file_path = "../../other-directory/image.jpg"
    assert not service._snapshot_has_persisted_file(snapshot=_snapshot(asset))
    assert service.resolve_file_path(asset=asset) is None
