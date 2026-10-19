"""RC5.6–RC5.8: data integrity, bounded downloads, retry and operator reports."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from http.client import IncompleteRead
from pathlib import Path
from threading import Event, Lock, current_thread
from time import sleep
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

from app.crawler.instagram.dto import (
    InstagramAssetDTO, InstagramAssetType, InstagramMediaDTO, InstagramMediaType,
)
from app.crawler.instagram.playwright_provider import PlaywrightInstagramProvider
from app.extensions import db
from app.repositories.instagram_source_repository import InstagramSourceRepository
from app.services.crawl_job_progress import CrawlCancelled
from app.services.crawl_run_audit import CrawlRunAudit
from app.services.media_storage_service import (
    InstagramMediaStorageService, _AssetSnapshot, _PersistedFile,
)


def _snapshot(n: int) -> _AssetSnapshot:
    return _AssetSnapshot(
        asset_id=f"asset-{n}", media_id=f"media-{n}", shortcode=f"CODE{n}",
        source_url=f"https://example.test/{n}.jpg", asset_type="image",
        position=0, local_file_path=None, local_file_status="missing",
        local_file_error=None,
    )


def _persisted(n: int) -> _PersistedFile:
    return _PersistedFile(relative_path=f"shop/CODE{n}/asset-{n}.jpg",
                          content_type="image/jpeg", size_bytes=256,
                          sha256="a" * 64, saved_at=datetime.now(timezone.utc))


def test_run_audit_separates_attempts_and_persists_without_secrets(tmp_path: Path) -> None:
    audit = CrawlRunAudit(tmp_path)
    first = audit.begin("source-1", requested=5, sort_order="newest", signed_in=True)
    audit.update("source-1", metrics={
        "discovered_candidates": 8, "detail_attempted": 8,
        "detail_succeeded": 8, "unique_valid": 8, "selected_posts": 5,
        "synced_posts": 5, "download_saved": 4, "download_reused": 3,
        "bytes_downloaded": 1024,
        "cookie_value": "should-not-be-stored", "raw_url": "secret",
    })
    audit.finish("source-1", status="completed")
    latest = CrawlRunAudit(tmp_path).latest("source-1")
    assert latest is not None and latest["run_id"] == first
    assert latest["discovered_candidates"] == 8
    assert latest["selected_posts"] == latest["synced_posts"] == 5
    assert latest["duration_seconds"] >= 0
    serialized = (tmp_path / "source-1" / f"{first}.json").read_text()
    assert "cookie_value" not in serialized and "raw_url" not in serialized
    second = audit.begin("source-1", requested=10, sort_order="oldest", signed_in=False)
    audit.update("source-1", metrics={"detail_failed": 2})
    audit.finish("source-1", status="cancelled")
    history = CrawlRunAudit(tmp_path).history("source-1")
    assert [item["run_id"] for item in history] == [second, first]
    assert history[0]["status"] == "cancelled" and history[1]["status"] == "completed"


def test_abandoned_run_is_displayed_as_interrupted(tmp_path: Path) -> None:
    audit = CrawlRunAudit(tmp_path)
    audit.begin("source-2", requested=20, sort_order="newest", signed_in=False)
    assert CrawlRunAudit(tmp_path).latest("source-2")["status"] == "interrupted"
    assert audit.latest("source-2")["status"] == "running"
    with pytest.raises(ValueError):
        audit.history("../evil")


def test_provider_reports_pinned_overscan_separately() -> None:
    provider = PlaywrightInstagramProvider(headless=True)
    urls = [f"https://www.instagram.com/p/CODE{i}/" for i in range(8)]
    fake_browser = MagicMock()
    fake_media = [SimpleNamespace(shortcode=f"CODE{i}",
                                  published_at=datetime(2026, 10, 19, tzinfo=timezone.utc))
                  for i in range(8)]
    with patch.object(provider, "_browser_context", return_value=nullcontext(fake_browser)), \
         patch.object(provider, "_discover_media_urls", return_value=tuple(urls)), \
         patch.object(provider, "_fetch_media_detail", side_effect=fake_media):
        result = provider.fetch_media(username="testshop", max_items=5)
    assert len(result) == 5
    assert provider.discovery_metrics == {
        "discovered_candidates": 8, "detail_attempted": 8, "detail_failed": 0,
        "detail_succeeded": 8, "unique_valid": 8, "selected_posts": 5,
    }


def test_transient_http_503_retries_but_permanent_403_does_not(tmp_path: Path) -> None:
    service = InstagramMediaStorageService(root_path=str(tmp_path), timeout_seconds=2,
                                           max_bytes=1024 * 1024)
    transient = HTTPError("https://example.test", 503, "Busy", {}, None)
    forbidden = HTTPError("https://example.test", 403, "Forbidden", {}, None)
    with patch.object(service, "_persist_snapshot", side_effect=[transient, _persisted(1)]) as download:
        assert service._download_with_retry(snapshot=_snapshot(1), username="shop").size_bytes == 256
        assert download.call_count == 2
    with patch.object(service, "_persist_snapshot", side_effect=forbidden) as download:
        with pytest.raises(HTTPError):
            service._download_with_retry(snapshot=_snapshot(1), username="shop")
        assert download.call_count == 1
    assert service._retryable(URLError("connection reset"))
    assert service._retryable(IncompleteRead(b"", 10))


def _media(n: int) -> InstagramMediaDTO:
    return InstagramMediaDTO(
        media_id=f"insta-{n}", shortcode=f"CODE{n}", media_type=InstagramMediaType.IMAGE,
        permalink=f"https://www.instagram.com/p/CODE{n}/",
        assets=(InstagramAssetDTO(asset_type=InstagramAssetType.IMAGE,
                                  source_url=f"https://example.test/{n}.jpg", position=0),),
    )


def test_parallel_downloads_keep_all_sqlalchemy_writes_on_owner_thread(app, tmp_path: Path) -> None:
    with app.app_context():
        repo = InstagramSourceRepository()
        source = repo.create(username="parallel_test")
        repo.sync_media(source=source, media_items=tuple(_media(n) for n in range(6)), full_sync=False)
        storage = InstagramMediaStorageService(root_path=str(tmp_path), timeout_seconds=2,
                                               max_bytes=1024 * 1024)
        owner_thread = current_thread().name
        worker_names: set[str] = set()
        writing_threads: list[str] = []
        lock = Lock()
        original_write = storage._write_asset_state

        def simulate_download(*, snapshot, username, check_cancel):
            with lock:
                worker_names.add(current_thread().name)
            sleep(0.012)
            return _PersistedFile(relative_path=f"{username}/{snapshot.asset_id}.jpg",
                                  content_type="image/jpeg", size_bytes=512,
                                  sha256="a" * 64, saved_at=datetime.now(timezone.utc))

        def observed_write(*, asset_id, values):
            writing_threads.append(current_thread().name)
            return original_write(asset_id=asset_id, values=values)

        with patch.object(storage, "_download_with_retry", side_effect=simulate_download), \
             patch.object(storage, "_write_asset_state", side_effect=observed_write):
            result = storage.persist_source(source=source)
        assert result.saved == 6 and result.failed == 0
        assert result.bytes_saved == 3072
        assert len(worker_names) >= 2 and len(worker_names) <= 3
        assert all(thread == owner_thread for thread in writing_threads)


def test_parallel_cancel_keeps_database_consistent(app, tmp_path: Path) -> None:
    with app.app_context():
        repo = InstagramSourceRepository()
        source = repo.create(username="cancel_parallel")
        repo.sync_media(source=source, media_items=tuple(_media(n) for n in range(5)), full_sync=False)
        storage = InstagramMediaStorageService(root_path=str(tmp_path), timeout_seconds=2,
                                               max_bytes=1024 * 1024)
        cancelled = Event()

        def download(*, snapshot, username, check_cancel):
            cancelled.set()
            check_cancel()
            return _persisted(1)

        def check_cancel():
            if cancelled.is_set():
                raise CrawlCancelled()

        with patch.object(storage, "_download_with_retry", side_effect=download):
            with pytest.raises(CrawlCancelled):
                storage.persist_source(source=source, check_cancel=check_cancel)
        assert not list(tmp_path.rglob("*.part"))
        assert not list(tmp_path.rglob("*.jpg"))


def test_retry_route_does_not_auto_select_previous_operator(client, app) -> None:
    with app.app_context():
        source = InstagramSourceRepository().create(username="safe_retry_shop")
        source_id = source.id
    response = client.get(f"/crawl/{source_id}/retry", follow_redirects=True)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'value="safe_retry_shop"' in html
    assert 'name="instagram_account"' in html
    assert client.get(f"/crawl/{source_id}/report").get_json() == {"runs": []}
    assert client.get("/crawl/no-such-id/retry").status_code == 404


def test_existing_media_is_not_unavailable_after_shorter_partial_crawl(app) -> None:
    with app.app_context():
        repo = InstagramSourceRepository()
        source = repo.create(username="non_destructive_recheck")
        repo.sync_media(source=source, media_items=tuple(_media(n) for n in range(9)), full_sync=True)
        # An anonymous session might see only five posts next time.
        repo.sync_media(source=source, media_items=tuple(_media(n) for n in range(5)), full_sync=False)
        assert sum(bool(m.is_available) for m in source.media) == 9
        assert source.crawled_media_count == 5  # latest run only
