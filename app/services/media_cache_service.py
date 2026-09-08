from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import mimetypes
import os
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from sqlalchemy import select

from app.extensions import db
from app.models import InstagramAsset, InstagramMedia, InstagramSource


@dataclass(frozen=True, slots=True)
class MediaCacheResult:
    cached: int
    reused: int
    failed: int


class MediaCacheError(RuntimeError):
    pass


class InstagramMediaCacheService:
    """
    Disposable local cache for Instagram CDN assets.

    The cache is an operator convenience layer only. It is not Selora's
    canonical media storage. A valid existing cache file is deliberately
    reused when Instagram rotates/refreshes the CDN URL.
    """

    CHUNK_SIZE = 64 * 1024

    def __init__(
        self,
        *,
        root_path: str,
        timeout_seconds: int,
        max_bytes: int,
    ) -> None:
        self._root = Path(root_path).resolve()
        self._timeout_seconds = timeout_seconds
        self._max_bytes = max_bytes

    def cache_source(
        self,
        *,
        source: InstagramSource,
    ) -> MediaCacheResult:
        assets = tuple(
            db.session.scalars(
                select(InstagramAsset)
                .join(
                    InstagramMedia,
                    InstagramAsset.media_id
                    == InstagramMedia.id,
                )
                .where(
                    InstagramMedia.source_id
                    == source.id,
                    InstagramAsset.is_available.is_(True),
                )
                .order_by(
                    InstagramMedia.position,
                    InstagramAsset.position,
                    InstagramAsset.id,
                )
            ).all()
        )

        cached = 0
        reused = 0
        failed = 0

        for asset in assets:
            media = asset.media

            try:
                if self._has_valid_cache(asset=asset):
                    asset.local_cache_status = "ready"
                    asset.local_cache_error = None
                    reused += 1
                    continue

                self._cache_asset(
                    asset=asset,
                    username=source.username,
                    shortcode=media.shortcode,
                )
                cached += 1

            except Exception as exc:
                asset.local_cache_status = "failed"
                asset.local_cache_error = str(exc).strip()[:2000]
                failed += 1

        db.session.commit()

        return MediaCacheResult(
            cached=cached,
            reused=reused,
            failed=failed,
        )

    def resolve_cache_path(
        self,
        *,
        asset: InstagramAsset,
    ) -> Path | None:
        raw_path = (
            asset.local_cache_path or ""
        ).strip()

        if not raw_path:
            return None

        candidate = (
            self._root
            / Path(raw_path)
        ).resolve()

        try:
            candidate.relative_to(
                self._root
            )
        except ValueError:
            return None

        return candidate

    def _has_valid_cache(
        self,
        *,
        asset: InstagramAsset,
    ) -> bool:
        path = self.resolve_cache_path(
            asset=asset
        )

        if path is None:
            return False

        try:
            return (
                path.is_file()
                and path.stat().st_size > 0
            )
        except OSError:
            return False

    def _cache_asset(
        self,
        *,
        asset: InstagramAsset,
        username: str,
        shortcode: str,
    ) -> None:
        source_url = asset.source_url.strip()

        if not source_url:
            raise MediaCacheError(
                "Instagram asset has no source URL."
            )

        request = Request(
            source_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/152.0 Safari/537.36"
                ),
                "Accept": "image/*,video/*,*/*;q=0.8",
            },
        )

        with urlopen(
            request,
            timeout=self._timeout_seconds,
        ) as response:
            content_type = (
                response.headers
                .get_content_type()
                .strip()
                .lower()
            )

            content_length = (
                response.headers.get(
                    "Content-Length"
                )
            )

            if content_length:
                try:
                    announced_size = int(
                        content_length
                    )
                except ValueError:
                    announced_size = 0

                if (
                    announced_size
                    > self._max_bytes
                ):
                    raise MediaCacheError(
                        (
                            "Instagram asset exceeds "
                            "local cache size limit."
                        )
                    )

            extension = self._choose_extension(
                content_type=content_type,
                source_url=source_url,
            )

            relative_path = self._build_relative_path(
                username=username,
                shortcode=shortcode,
                asset=asset,
                extension=extension,
            )

            destination = (
                self._root
                / relative_path
            ).resolve()

            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            temp_path = destination.with_suffix(
                destination.suffix + ".part"
            )

            digest = hashlib.sha256()
            file_size = 0

            try:
                with temp_path.open("wb") as output:
                    while True:
                        chunk = response.read(
                            self.CHUNK_SIZE
                        )

                        if not chunk:
                            break

                        file_size += len(chunk)

                        if file_size > self._max_bytes:
                            raise MediaCacheError(
                                (
                                    "Instagram asset exceeds "
                                    "local cache size limit."
                                )
                            )

                        digest.update(chunk)
                        output.write(chunk)

                if file_size <= 0:
                    raise MediaCacheError(
                        "Instagram asset download was empty."
                    )

                os.replace(
                    temp_path,
                    destination,
                )

            finally:
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass

        asset.local_cache_path = (
            relative_path.as_posix()
        )
        asset.local_cache_status = "ready"
        asset.local_cached_at = datetime.now(
            timezone.utc
        )
        asset.local_content_type = (
            content_type or None
        )
        asset.local_file_size = file_size
        asset.local_sha256 = digest.hexdigest()
        asset.local_cache_error = None

    @staticmethod
    def _safe_segment(
        value: str,
        *,
        fallback: str,
    ) -> str:
        cleaned = "".join(
            char
            if (
                char.isalnum()
                or char in {
                    "-",
                    "_",
                    ".",
                }
            )
            else "_"
            for char in value.strip()
        ).strip("._")

        return cleaned or fallback

    def _build_relative_path(
        self,
        *,
        username: str,
        shortcode: str,
        asset: InstagramAsset,
        extension: str,
    ) -> Path:
        safe_username = self._safe_segment(
            username,
            fallback="instagram",
        )
        safe_shortcode = self._safe_segment(
            shortcode,
            fallback=str(asset.media_id),
        )
        safe_type = self._safe_segment(
            asset.asset_type,
            fallback="asset",
        )

        filename = (
            f"asset_{int(asset.position):03d}_"
            f"{safe_type}_{asset.id}.{extension}"
        )

        return Path(
            safe_username,
            safe_shortcode,
            filename,
        )

    @staticmethod
    def _choose_extension(
        *,
        content_type: str,
        source_url: str,
    ) -> str:
        explicit = {
            "image/jpeg": "jpg",
            "image/jpg": "jpg",
            "image/png": "png",
            "image/webp": "webp",
            "image/gif": "gif",
            "video/mp4": "mp4",
            "video/webm": "webm",
            "video/quicktime": "mov",
        }.get(content_type)

        if explicit:
            return explicit

        guessed = mimetypes.guess_extension(
            content_type
        )

        if guessed:
            normalized = guessed.lstrip(
                "."
            ).lower()

            if (
                normalized.isalnum()
                and len(normalized) <= 8
            ):
                return normalized

        url_suffix = Path(
            urlparse(source_url).path
        ).suffix.lstrip(".").lower()

        if (
            url_suffix.isalnum()
            and len(url_suffix) <= 8
        ):
            return url_suffix

        return "bin"
