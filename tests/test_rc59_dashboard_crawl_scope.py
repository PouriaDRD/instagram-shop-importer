"""RC5.9: dashboard/start separation, backward compatibility and media scoping."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from flask.testing import FlaskClient

from app.extensions import db
from app.repositories.instagram_source_repository import InstagramSourceRepository
from app.services.instagram_sync_service import InstagramSyncService
from app.services.media_storage_service import InstagramMediaStorageService, MediaStorageResult
from app.crawler.instagram.dto import InstagramAssetDTO, InstagramAssetType, InstagramMediaDTO, InstagramMediaType


def media(n: int) -> InstagramMediaDTO:
    return InstagramMediaDTO(
        media_id=f"rc59-post-{n}", shortcode=f"NEW{n}",
        media_type=InstagramMediaType.IMAGE,
        permalink=f"https://www.instagram.com/p/NEW{n}/",
        assets=(InstagramAssetDTO(asset_type=InstagramAssetType.IMAGE,
                                   source_url=f"https://example.test/{n}.jpg", position=0),),
    )


def test_dashboard_and_start_are_separate(client: FlaskClient) -> None:
    dash = client.get("/")
    assert dash.status_code == 200
    assert "مرکز مدیریت انتقال اینستاگرام" in dash.get_data(as_text=True)
    assert 'id="crawlForm"' not in dash.get_data(as_text=True)
    start = client.get("/crawl/new")
    assert start.status_code == 200
    html = start.get_data(as_text=True)
    for term in ('id="crawlForm"', 'id="crawlStopButton"', 'name="sort_order"',
                 'name="instagram_account"', 'id="crawlViewResults"'):
        assert term in html
    assert 'action="/crawl"' in html
    old = client.get("/crawl")
    assert old.status_code in (301, 302, 307, 308)
    assert old.headers['Location'].endswith('/crawl/new')


def test_dashboard_counts_connected_account_dicts(client, app, monkeypatch) -> None:
    """Account registry returns dicts, not objects with .saved_session."""
    manager = app.extensions["instagram_operator_accounts"]
    monkeypatch.setattr(manager, "list_accounts", lambda: [
        {"id": "a" * 32, "label": "connected", "saved_session": True},
        {"id": "b" * 32, "label": "expired", "saved_session": False},
        {"id": "c" * 32, "label": "not-yet-connected"},
    ])

    response = client.get("/")
    assert response.status_code == 200
    assert '<strong>1</strong><small>نشست ورود ذخیره‌شده</small>' in response.get_data(as_text=True)

    monkeypatch.setattr(manager, "list_accounts", lambda: [])
    response = client.get("/")
    assert response.status_code == 200
    assert '<strong>0</strong><small>نشست ورود ذخیره‌شده</small>' in response.get_data(as_text=True)


def test_retry_opens_separate_start_without_auto_selecting_account(client, app) -> None:
    with app.app_context():
        record = InstagramSourceRepository().create(username="rc59_restart")
        sid = record.id
    resp = client.get(f"/crawl/{sid}/retry")
    assert resp.status_code == 302
    assert '/crawl/new?' in resp.headers['Location']
    html = client.get(resp.headers['Location']).get_data(as_text=True)
    assert 'value="rc59_restart"' in html
    assert '<option value="">بدون ورود' in html


def test_dashboard_recent_sources_and_stats(client, app) -> None:
    with app.app_context():
        src = InstagramSourceRepository().create(username="rc59_recent")
        src.status = "completed"
        db.session.commit()
    html = client.get('/').get_data(as_text=True)
    assert 'rc59_recent' in html
    assert 'کراول تکمیل‌شده' in html
    assert 'مشاهده نشست‌ها' in html


def test_only_this_runs_assets_are_passed_to_media_storage(app, tmp_path: Path) -> None:
    with app.app_context():
        repo = InstagramSourceRepository()
        src = repo.create(username="rc59_scope")
        repo.sync_media(session=src, media_items=tuple(media(n) for n in range(6)), full_sync=False)
        storage = InstagramMediaStorageService(root_path=str(tmp_path), timeout_seconds=2, max_bytes=1024 * 1024)
        service = InstagramSyncService(provider=None, repository=repo, media_storage_service=storage)
        selected = (media(2), media(4))
        with patch.object(storage, 'persist_source') as persist:
            persist.return_value = MediaStorageResult(saved=0, reused=2, failed=0, bytes_saved=0)
            service._persist_media_files_safely(source=src, media_items=selected)
            call = persist.call_args.kwargs
        assert call['parallel_downloads'] is True
        assert {asset.media.media_id for asset in call['assets']} == {'rc59-post-2','rc59-post-4'}
        assert len(call['assets']) == 2


def test_empty_selected_run_does_not_fall_back_to_all_assets(app, tmp_path: Path) -> None:
    with app.app_context():
        repo=InstagramSourceRepository();src=repo.create(username='rc59_empty')
        repo.sync_media(session=src, media_items=(media(1),), full_sync=False)
        storage=InstagramMediaStorageService(root_path=str(tmp_path), timeout_seconds=2,max_bytes=2048)
        service=InstagramSyncService(provider=None,repository=repo,media_storage_service=storage)
        with patch.object(storage,'persist_source') as persist:
            persist.return_value=MediaStorageResult(saved=0,reused=0,failed=0,bytes_saved=0)
            service._persist_media_files_safely(source=src,media_items=())
        assert persist.call_args.kwargs['assets'] == ()


def test_local_navigation_links_point_to_crawl_new() -> None:
    root=Path(__file__).resolve().parents[1]
    for file in ['base.html','crawl_list.html','crawl_detail.html','instagram_accounts.html','import_success.html']:
        text=(root/'app'/'templates'/file).read_text(encoding='utf8')
        assert "url_for('web.crawl_new')" in text
    assert "url_for('web.index')" in (root/'app/templates/base.html').read_text(encoding='utf8')
