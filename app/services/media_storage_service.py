from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from http.client import IncompleteRead
from urllib.error import HTTPError, URLError
from datetime import datetime, timezone
import hashlib
import logging
import mimetypes
import os
from pathlib import Path
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.services.crawl_job_progress import CrawlCancelled
from app.extensions import db
from app.models import InstagramAsset, InstagramMedia, InstagramSource


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MediaStorageResult:
    saved: int
    reused: int
    failed: int
    bytes_saved: int = 0


@dataclass(frozen=True, slots=True)
class _AssetSnapshot:
    asset_id: str
    source_url: str
    media_id: str
    shortcode: str
    asset_type: str
    position: int
    local_file_path: str | None
    local_file_status: str
    local_file_error: str | None


@dataclass(frozen=True, slots=True)
class _PersistedFile:
    relative_path: str
    content_type: str | None
    size_bytes: int
    sha256: str
    saved_at: datetime


class MediaStorageError(RuntimeError):
    pass


class InstagramMediaStorageService:
    """
    Disposable persistent local storage for Instagram CDN assets.

    Network I/O is deliberately performed with no open SQLAlchemy write
    transaction. Each asset state update is committed separately, so a slow or
    unavailable CDN cannot hold SQLite locks for minutes.
    """

    CHUNK_SIZE = 64 * 1024
    DB_COMMIT_ATTEMPTS = 4
    DB_LOCK_BACKOFF_SECONDS = 0.25
    MAX_DOWNLOAD_WORKERS = 3
    MAX_DOWNLOAD_ATTEMPTS = 3

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

    def persist_source(
        self,
        *,
        source: InstagramSource,
        assets: Iterable[InstagramAsset] | None = None,
        parallel_downloads: bool = False,
        check_cancel: Callable[[], None] | None = None,
        on_progress: Callable[..., None] | None = None,
    ) -> MediaStorageResult:
        """
        Persist media for a source or an explicitly supplied asset subset.

        The subset mode is used by the interactive Selora send path so one
        missing selected image never triggers downloads for unrelated media.
        """
        source_id = str(source.id)
        username = source.username

        if assets is None:
            persisted_assets = tuple(
                db.session.scalars(
                    select(InstagramAsset)
                    .join(
                        InstagramMedia,
                        InstagramAsset.media_id == InstagramMedia.id,
                    )
                    .where(
                        InstagramMedia.source_id == source.id,
                        InstagramAsset.is_available.is_(True),
                    )
                    .order_by(
                        InstagramMedia.position,
                        InstagramAsset.position,
                        InstagramAsset.id,
                    )
                ).all()
            )
        else:
            persisted_assets = tuple(assets)

        snapshots = tuple(
            self._snapshot(asset=asset)
            for asset in persisted_assets
        )

        logger.info(
            (
                "Media persistence started: "
                "source_id=%s username=%s assets=%s root=%s"
            ),
            source_id,
            username,
            len(snapshots),
            self._root,
        )

        # End the read transaction before any CDN/network operation. The old
        # implementation kept this transaction alive for the entire batch and
        # committed all failures at the end, which amplified SQLite locking.
        db.session.commit()

        saved = reused = failed = bytes_saved = 0
        completed = 0
        total = len(snapshots)

        def progress() -> None:
            if on_progress:
                on_progress("downloading", completed, total, saved=saved,
                            reused=reused, failed=failed, bytes_saved=bytes_saved)

        progress()

        # Only workers handle immutable DTOs and network/file I/O. The Flask
        # application context and SQLite session remain on THIS thread.
        # Explicit subsets (e.g. Selora upload of one asset) stay serial.
        parallelism = (
            min(self.MAX_DOWNLOAD_WORKERS, total)
            if assets is None or parallel_downloads else 1
        )

        def process(snapshot: _AssetSnapshot, persisted: _PersistedFile | None,
                    error: Exception | None) -> None:
            nonlocal saved, failed, bytes_saved, completed
            if check_cancel:
                check_cancel()
            try:
                if error is not None:
                    raise error
                if persisted is None:
                    raise MediaStorageError("Download returned no media")
                self._write_asset_state(asset_id=snapshot.asset_id, values={
                    "local_file_path": persisted.relative_path,
                    "local_file_status": "ready", "local_saved_at": persisted.saved_at,
                    "local_content_type": persisted.content_type,
                    "local_file_size": persisted.size_bytes,
                    "local_sha256": persisted.sha256,
                    "local_file_error": None,
                })
                saved += 1
                bytes_saved += persisted.size_bytes
            except CrawlCancelled:
                raise
            except Exception as exc:
                failed += 1
                try:
                    self._write_asset_state(asset_id=snapshot.asset_id, values={
                        "local_file_status": "failed", "local_file_error": str(exc).strip()[:2000],
                    })
                except Exception:
                    logger.exception("Failed to save media failure state: %s", snapshot.asset_id)
                logger.warning("Media asset failed: media=%s asset=%s type=%s error=%s",
                               snapshot.media_id, snapshot.asset_id,
                               type(exc).__name__, str(exc)[:160])
            finally:
                completed += 1
                progress()

        pending_downloads: list[_AssetSnapshot] = []
        for snapshot in snapshots:
            if check_cancel:
                check_cancel()
            if self._snapshot_has_persisted_file(snapshot=snapshot):
                try:
                    self._write_asset_state(asset_id=snapshot.asset_id,
                                            values={"local_file_status": "ready", "local_file_error": None})
                    reused += 1
                    completed += 1
                    progress()
                except Exception as exc:
                    process(snapshot, None, exc)
            else:
                pending_downloads.append(snapshot)

        if pending_downloads:
            if parallelism <= 1:
                for snapshot in pending_downloads:
                    if check_cancel:
                        check_cancel()
                    try:
                        persisted = self._download_with_retry(
                            snapshot=snapshot, username=username, check_cancel=check_cancel,
                        )
                    except CrawlCancelled:
                        raise
                    except Exception as exc:
                        process(snapshot, None, exc)
                    else:
                        process(snapshot, persisted, None)
            else:
                executor = ThreadPoolExecutor(max_workers=parallelism,
                                              thread_name_prefix="instagram-media")
                futures: dict[Future[_PersistedFile], _AssetSnapshot] = {}
                try:
                    for snapshot in pending_downloads:
                        if check_cancel:
                            check_cancel()
                        future = executor.submit(self._download_with_retry,
                                                 snapshot=snapshot, username=username,
                                                 check_cancel=check_cancel)
                        futures[future] = snapshot
                    waiting = set(futures)
                    while waiting:
                        if check_cancel:
                            check_cancel()
                        done, waiting = wait(waiting, timeout=0.3,
                                             return_when=FIRST_COMPLETED)
                        for future in done:
                            if check_cancel:
                                check_cancel()
                            snapshot = futures[future]
                            try:
                                persisted = future.result()
                            except CrawlCancelled:
                                raise
                            except Exception as exc:
                                process(snapshot, None, exc)
                            else:
                                process(snapshot, persisted, None)
                except BaseException:
                    for future in futures:
                        future.cancel()
                    raise
                finally:
                    # All opened streams close (and .part files are removed)
                    # before the crawl worker can report a terminal status.
                    executor.shutdown(wait=True, cancel_futures=True)

        logger.info("Media persistence completed: source_id=%s saved=%s reused=%s failed=%s bytes=%s",
                    source_id, saved, reused, failed, bytes_saved)
        return MediaStorageResult(saved=saved, reused=reused, failed=failed,
                                  bytes_saved=bytes_saved)

    @staticmethod
    def _retryable(exc: Exception) -> bool:
        if isinstance(exc, HTTPError):
            return exc.code in {408, 429, 500, 502, 503, 504}
        return isinstance(exc, (URLError, TimeoutError, ConnectionResetError, IncompleteRead))

    def _download_with_retry(self, *, snapshot: _AssetSnapshot,
                             username: str,
                             check_cancel: Callable[[], None] | None = None) -> _PersistedFile:
        start = time.monotonic()
        # Soft overall budget; a blocked socket read remains bounded by the
        # socket timeout. This does not forcibly terminate OS network calls.
        budget = max(15, min(self._timeout_seconds * 4, 180))
        deadline = start + budget
        for attempt in range(1, self.MAX_DOWNLOAD_ATTEMPTS + 1):
            if check_cancel:
                check_cancel()
            try:
                return self._persist_snapshot(snapshot=snapshot, username=username,
                                              check_cancel=check_cancel,
                                              deadline_monotonic=deadline)
            except CrawlCancelled:
                raise
            except Exception as exc:
                if (attempt == self.MAX_DOWNLOAD_ATTEMPTS or
                    not self._retryable(exc) or time.monotonic() - start >= budget):
                    raise
                delay = min(0.7 * (2 ** (attempt - 1)), 4.0)
                if isinstance(exc, HTTPError) and exc.headers:
                    retry_after = exc.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        delay = max(delay, min(float(retry_after), 10.0))
                logger.info("Transient media error: retrying asset=%s attempt=%s/%s",
                            snapshot.asset_id, attempt, self.MAX_DOWNLOAD_ATTEMPTS)
                # Check cooperative stop frequently instead of sleep() for the
                # entire delay. No aggressive retry storm on rate limiting.
                until = time.monotonic() + delay
                while time.monotonic() < until:
                    if check_cancel:
                        check_cancel()
                    time.sleep(max(0, min(0.2, until - time.monotonic())))
        raise AssertionError("Download retry loop exhausted")

    def resolve_file_path(
        self,
        *,
        asset: InstagramAsset,
    ) -> Path | None:
        return self._resolve_relative_path(
            raw_path=(asset.local_file_path or "").strip()
        )

    def _snapshot(
        self,
        *,
        asset: InstagramAsset,
    ) -> _AssetSnapshot:
        media = asset.media
        return _AssetSnapshot(
            asset_id=str(asset.id),
            source_url=(asset.source_url or "").strip(),
            media_id=str(media.media_id),
            shortcode=media.shortcode,
            asset_type=asset.asset_type,
            position=int(asset.position),
            local_file_path=asset.local_file_path,
            local_file_status=asset.local_file_status,
            local_file_error=asset.local_file_error,
        )

    def _snapshot_has_persisted_file(
        self,
        *,
        snapshot: _AssetSnapshot,
    ) -> bool:
        path = self._resolve_relative_path(
            raw_path=(snapshot.local_file_path or "").strip()
        )
        if path is None:
            return False

        try:
            return path.is_file() and path.stat().st_size > 0
        except OSError:
            return False

    def _resolve_relative_path(
        self,
        *,
        raw_path: str,
    ) -> Path | None:
        if not raw_path:
            return None

        candidate = (self._root / Path(raw_path)).resolve()
        try:
            candidate.relative_to(self._root)
        except ValueError:
            return None
        return candidate

    def _write_asset_state(
        self,
        *,
        asset_id: str,
        values: dict[str, object],
    ) -> None:
        for attempt in range(1, self.DB_COMMIT_ATTEMPTS + 1):
            try:
                asset = db.session.get(InstagramAsset, asset_id)
                if asset is None:
                    raise MediaStorageError(
                        f"Instagram asset disappeared during persistence: {asset_id}"
                    )

                for key, value in values.items():
                    setattr(asset, key, value)

                db.session.commit()
                return

            except OperationalError as exc:
                db.session.rollback()
                locked = "database is locked" in str(exc).lower()
                if not locked or attempt >= self.DB_COMMIT_ATTEMPTS:
                    raise

                delay = self.DB_LOCK_BACKOFF_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    (
                        "SQLite busy while saving media state; retrying: "
                        "asset_id=%s attempt=%s/%s delay=%.2fs"
                    ),
                    asset_id,
                    attempt,
                    self.DB_COMMIT_ATTEMPTS,
                    delay,
                )
                time.sleep(delay)

            except Exception:
                db.session.rollback()
                raise

    def _persist_snapshot(
        self,
        *,
        snapshot: _AssetSnapshot,
        username: str,
        check_cancel: Callable[[], None] | None = None,
        deadline_monotonic: float | None = None,
    ) -> _PersistedFile:
        source_url = snapshot.source_url
        if not source_url:
            raise MediaStorageError("Instagram asset has no source URL.")

        request = Request(
            source_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/152.0 Safari/537.36"
                ),
                "Accept": "image/*,video/*,*/*;q=0.8",
            },
        )

        deadline = deadline_monotonic or (
            time.monotonic() + max(15, min(self._timeout_seconds * 4, 180))
        )
        with urlopen(request, timeout=self._timeout_seconds) as response:
            content_type = response.headers.get_content_type().strip().lower()
            content_length = response.headers.get("Content-Length")

            if content_length:
                try:
                    announced_size = int(content_length)
                except ValueError:
                    announced_size = 0
                if announced_size > self._max_bytes:
                    raise MediaStorageError(
                        "Instagram asset exceeds persistent local storage size limit."
                    )

            extension = self._choose_extension(
                content_type=content_type,
                source_url=source_url,
            )
            relative_path = self._build_relative_path(
                username=username,
                shortcode=snapshot.shortcode,
                snapshot=snapshot,
                extension=extension,
            )
            destination = (self._root / relative_path).resolve()
            destination.parent.mkdir(parents=True, exist_ok=True)
            temp_path = destination.with_suffix(destination.suffix + ".part")

            digest = hashlib.sha256()
            file_size = 0

            try:
                with temp_path.open("wb") as output:
                    while True:
                        if check_cancel:
                            check_cancel()
                        if time.monotonic() > deadline:
                            raise TimeoutError("Media transfer exceeded its time budget")
                        chunk = response.read(self.CHUNK_SIZE)
                        if time.monotonic() > deadline:
                            raise TimeoutError("Media transfer exceeded its time budget")
                        if not chunk:
                            break
                        file_size += len(chunk)
                        if file_size > self._max_bytes:
                            raise MediaStorageError(
                                "Instagram asset exceeds persistent local storage size limit."
                            )
                        digest.update(chunk)
                        output.write(chunk)

                if file_size <= 0:
                    raise MediaStorageError("Instagram asset download was empty.")

                os.replace(temp_path, destination)
            finally:
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass

        return _PersistedFile(
            relative_path=relative_path.as_posix(),
            content_type=content_type or None,
            size_bytes=file_size,
            sha256=digest.hexdigest(),
            saved_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _safe_segment(
        value: str,
        *,
        fallback: str,
    ) -> str:
        cleaned = "".join(
            char
            if char.isalnum() or char in {"-", "_", "."}
            else "_"
            for char in value.strip()
        ).strip("._")
        return cleaned or fallback

    def _build_relative_path(
        self,
        *,
        username: str,
        shortcode: str,
        snapshot: _AssetSnapshot,
        extension: str,
    ) -> Path:
        safe_username = self._safe_segment(username, fallback="instagram")
        safe_shortcode = self._safe_segment(
            shortcode,
            fallback=snapshot.media_id,
        )
        safe_type = self._safe_segment(snapshot.asset_type, fallback="asset")
        filename = (
            f"asset_{snapshot.position:03d}_{safe_type}_"
            f"{snapshot.asset_id}.{extension}"
        )
        return Path(safe_username, safe_shortcode, filename)

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

        guessed = mimetypes.guess_extension(content_type)
        if guessed:
            normalized = guessed.lstrip(".").lower()
            if normalized.isalnum() and len(normalized) <= 8:
                return normalized

        url_suffix = Path(urlparse(source_url).path).suffix.lstrip(".").lower()
        if url_suffix.isalnum() and len(url_suffix) <= 8:
            return url_suffix

        return "bin"
