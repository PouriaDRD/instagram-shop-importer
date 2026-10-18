from __future__ import annotations

from flask import Flask
from flask.testing import FlaskClient

from app.extensions import db
from app.models.import_workspace import ImportWorkspace
from app.repositories import CrawlSessionRepository
from app.services.session_status_service import session_selora_status


def test_application_factory_registers_selora_status_helper(app: Flask) -> None:
    """The helper must exist without running the desktop entry point."""
    assert app.jinja_env.globals["session_selora_status"] is session_selora_status


def test_crawl_list_with_session_and_no_workspace_renders(app: Flask, client: FlaskClient) -> None:
    """An unsent crawl should render rather than return HTTP 500."""
    with app.app_context():
        CrawlSessionRepository().create(username="unsent_test_shop")
        db.session.commit()

    response = client.get("/crawls")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "unsent_test_shop" in html
    assert "ارسال نشده" in html


def test_crawl_list_shows_real_selora_send_error(app: Flask, client: FlaskClient) -> None:
    """A workspace's persisted Selora failure is visible to an operator."""
    with app.app_context():
        source = CrawlSessionRepository().create(username="error_test_shop")
        workspace = ImportWorkspace(source_id=source.id, local_sync_status="error")
        workspace.last_sync_error = "QA remote send failed"
        db.session.add(workspace)
        db.session.commit()

    response = client.get("/crawls")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "error_test_shop" in html
    assert "QA remote send failed" in html
    assert "ارسال ناموفق" in html
