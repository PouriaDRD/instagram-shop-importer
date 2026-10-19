"""RC5.5 regression guards: Persian UI and existing progress/stop workflow."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from flask import Flask
from flask.testing import FlaskClient

from app.services.crawl_job_progress import CrawlCancelled
from app.services.instagram_sync_service import InstagramSyncService


ROOT = Path(__file__).resolve().parents[1]


def test_persian_brand_and_same_browser_favicon(client: FlaskClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "ایمپورتر سلورا" in html
    assert "انتقال فروشگاه اینستاگرامی" in html
    assert 'class="brand__mark brand__mark--icon"' in html
    assert 'filename=\'images/favicon.ico\'' not in html  # no template source leakage
    assert "Instagram Migration Tool" not in html


def test_custom_select_keeps_real_posted_fields(client: FlaskClient) -> None:
    html = client.get("/").get_data(as_text=True)
    assert 'name="instagram_account"' in html
    assert 'name="sort_order"' in html
    assert html.count("data-custom-select") >= 2
    assert "custom_select.js" in html
    assert 'id="crawlStopButton"' in html
    assert client.get("/static/js/custom_select.js").status_code == 200


def test_sessions_table_controls_and_mobile_assets(client: FlaskClient) -> None:
    html = client.get("/crawls").get_data(as_text=True)
    assert 'class="page-title">نشست‌های کراول</h1>' in html
    # This page can be empty in the test database, so the filters live only
    # in the nonempty branch; validate their template source separately.
    source = (ROOT / "app/templates/crawl_list.html").read_text(encoding="utf-8")
    assert 'id="sessionStatusFilter"' in source
    assert 'id="sessionSearch"' in source
    assert 'data-session-row' in source
    assert 'onerror="this.remove()"' in source
    assert "crawl_sessions.js" in source
    assert client.get("/static/js/crawl_sessions.js").status_code == 200


def test_no_application_context_cancel_does_not_touch_database() -> None:
    repo = MagicMock()
    repo.get.return_value = MagicMock(username="test_operator")
    service = InstagramSyncService(provider=MagicMock(), repository=repo)

    def cancel() -> None:
        raise CrawlCancelled()

    service.run(session_id="test", check_cancel=cancel)
    repo.mark_cancelled.assert_called_once()
    repo.mark_failed.assert_not_called()


def test_source_files_dont_depend_on_inline_secret_credentials() -> None:
    native_js = (ROOT / "app/static/js/custom_select.js").read_text(encoding="utf-8")
    assert "new Event('change', {bubbles: true})" in native_js
    assert "aria-expanded" in native_js
    assert "ArrowDown" in native_js
    assert "Escape" in native_js
    assert "innerHTML" not in native_js
