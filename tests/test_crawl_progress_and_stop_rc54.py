"""RC5.4: progress accuracy, cooperative cancellation, authorization."""
from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from app.extensions import db
from app.repositories import CrawlSessionRepository
from app.services.crawl_job_progress import CrawlCancelled, CrawlJobProgress
from app.services.instagram_sync_service import InstagramSyncService


def test_progress_is_per_job_and_thread_safe() -> None:
    registry = CrawlJobProgress()
    registry.begin("a")
    registry.begin("b")
    registry.report("a", "downloading", 2, 4, saved=1, reused=1, bytes_saved=128)
    assert registry.snapshot("a")["current"] == 2
    assert registry.snapshot("b")["phase"] == "pending"
    assert registry.snapshot("a")["bytes_saved"] == 128
    assert registry.request_cancel("a") is True
    assert registry.request_cancel("a") is False
    registry.report("a", "downloading", 4, 4)  # cannot overwrite stopping phase
    assert registry.snapshot("a")["phase"] == "stopping"
    with pytest.raises(CrawlCancelled):
        registry.check("a")
    registry.check("b")
    registry.finish("a", "cancelled")
    assert registry.snapshot("a")["finished"] is True
    assert registry.request_cancel("a") is False
    registry.begin("a")  # a subsequent crawl of same source is allowed
    assert registry.snapshot("a")["cancel_requested"] is False


def test_concurrent_cancel_and_progress() -> None:
    registry = CrawlJobProgress()
    registry.begin("job")
    threads = [threading.Thread(target=lambda: [registry.report("job", "posts", n, 100) for n in range(100)])
               for _ in range(4)]
    for worker in threads: worker.start()
    for worker in threads: worker.join()
    assert registry.snapshot("job")["phase"] == "posts"
    assert registry.request_cancel("job")
    with pytest.raises(CrawlCancelled):
        registry.check("job")


def test_cancelled_service_does_not_mark_failed(app) -> None:
    source = MagicMock(username="test_shop")
    repository = MagicMock()
    repository.get.return_value = source
    service = InstagramSyncService(provider=MagicMock(), repository=repository)
    def cancel() -> None:
        raise CrawlCancelled()
    service.run(session_id="1", max_items=20, check_cancel=cancel)
    repository.mark_cancelled.assert_called_once_with(session=source)
    repository.mark_failed.assert_not_called()
    repository.sync_media.assert_not_called()
    repository.replace_media.assert_not_called()


def test_stop_endpoint_uses_csrf_and_loopback(app, client) -> None:
    with app.app_context():
        session = CrawlSessionRepository().create(username="stop_test_user")
        source_id = session.id
        app.extensions["crawl_job_progress"].begin(source_id)
        session.status = "running"
        db.session.commit()
    url = f"/crawl/{source_id}/stop"
    assert client.post(url).status_code == 403
    token = app.extensions["instagram_operator_csrf"]
    assert client.post(url, headers={"X-Crawl-Stop-Token": token}, environ_overrides={"REMOTE_ADDR": "192.0.2.10"}).status_code == 403
    assert client.post(url, headers={"X-Crawl-Stop-Token": token, "Origin": "https://attacker.test"}).status_code == 403
    ok = client.post(url, headers={"X-Crawl-Stop-Token": token})
    assert ok.status_code == 202
    assert ok.get_json()["status"] == "stopping"
    assert client.post(url, headers={"X-Crawl-Stop-Token": token}).status_code == 409
    status = client.get(f"/crawl/{source_id}/status")
    assert status.get_json()["progress"]["cancel_requested"] is True
    with app.app_context():
        assert CrawlSessionRepository().get(session_id=source_id).status == "running"
    # A stop request is not a completed cancellation until the worker handles it.
    assert client.get("/").status_code == 200
    assert b"crawlStopButton" in client.get("/").data


def test_existing_completed_session_cannot_be_cancelled(app, client) -> None:
    with app.app_context():
        source = CrawlSessionRepository().create(username="finished_test_user")
        source.status = "completed"
        db.session.commit()
        source_id = source.id
    token = app.extensions["instagram_operator_csrf"]
    response = client.post(f"/crawl/{source_id}/stop", headers={"X-Crawl-Stop-Token": token})
    assert response.status_code == 409
    assert response.get_json()["status"] == "completed"


def test_partial_download_is_removed_when_stopped(tmp_path) -> None:
    from email.message import Message
    from unittest.mock import patch
    from app.services.media_storage_service import InstagramMediaStorageService, _AssetSnapshot

    class Stream:
        def __init__(self):
            self.headers = Message()
            self.headers['Content-Type'] = 'image/jpeg'
            self.headers['Content-Length'] = str(512 * 1024)
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def read(self, _size): return b'a' * (64 * 1024)

    source = _AssetSnapshot(
        asset_id='uuid-a', source_url='https://instagram.example/a.jpg',
        media_id='media', shortcode='ABCD', asset_type='image', position=0,
        local_file_path=None, local_file_status='missing', local_file_error=None,
    )
    calls = [0]
    def check():
        calls[0] += 1
        if calls[0] >= 3:
            raise CrawlCancelled()
    service = InstagramMediaStorageService(root_path=str(tmp_path), timeout_seconds=3,
                                            max_bytes=1024*1024)
    with patch('app.services.media_storage_service.urlopen', return_value=Stream()):
        with pytest.raises(CrawlCancelled):
            service._persist_snapshot(snapshot=source, username='shop', check_cancel=check)
    assert calls[0] >= 3
    assert not list(tmp_path.rglob('*.part'))
    assert not list(tmp_path.rglob('*.jpg'))
