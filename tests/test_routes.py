from __future__ import annotations

from datetime import datetime, timezone

from flask import Flask
from flask.testing import FlaskClient

from app.extensions import db
from app.repositories import (
    CrawlSessionRepository,
)


def create_test_session(
    app: Flask,
    *,
    username: str = "test_user",
    status: str = "pending",
) -> str:
    with app.app_context():
        repository = CrawlSessionRepository()

        session = repository.create(username=username)

        session.status = status

        db.session.commit()

        return session.id


def test_home_page_returns_200(
    client: FlaskClient,
) -> None:
    response = client.get("/")

    assert response.status_code == 200


def test_crawl_list_returns_200(
    client: FlaskClient,
) -> None:
    response = client.get("/crawls")

    assert response.status_code == 200


def test_empty_crawl_list_does_not_crash(
    client: FlaskClient,
) -> None:
    response = client.get("/crawls")

    assert response.status_code == 200

    assert "هنوز نشستی وجود ندارد" in response.get_data(as_text=True)


def test_pending_session_detail_does_not_crash(
    app: Flask,
    client: FlaskClient,
) -> None:
    session_id = create_test_session(
        app,
        status="pending",
    )

    response = client.get(f"/crawl/{session_id}")

    assert response.status_code == 200


def test_session_with_all_optional_values_none_does_not_crash(
    app: Flask,
    client: FlaskClient,
) -> None:
    session_id = create_test_session(
        app,
        username="empty_profile",
    )

    response = client.get(f"/crawl/{session_id}")

    assert response.status_code == 200


def test_completed_session_detail_returns_200(
    app: Flask,
    client: FlaskClient,
) -> None:
    with app.app_context():
        repository = CrawlSessionRepository()

        session = repository.create(username="mahtabbeauty")

        session.status = "completed"

        session.full_name = "mahtab"

        session.followers_count = 1032
        session.following_count = 990

        session.crawled_media_count = 5

        session.started_at = datetime(
            2026,
            9,
            2,
            10,
            36,
            tzinfo=timezone.utc,
        )

        session.completed_at = datetime(
            2026,
            9,
            2,
            10,
            37,
            tzinfo=timezone.utc,
        )

        db.session.commit()

        session_id = session.id

    response = client.get(f"/crawl/{session_id}")

    assert response.status_code == 200

    html = response.get_data(as_text=True)

    assert "mahtab" in html
    assert "تکمیل‌شده" in html
    assert "زمان‌بندی نشست" in html
    assert "ایجاد نشست" in html
    assert "شروع کراول" in html
    assert "پایان کراول" in html


def test_unknown_session_returns_friendly_404(
    client: FlaskClient,
) -> None:
    response = client.get("/crawl/not-found")

    assert response.status_code == 404

    html = response.get_data(as_text=True)

    assert "صفحه پیدا نشد" in html


def test_get_crawl_redirects_home(
    client: FlaskClient,
) -> None:
    response = client.get("/crawl")

    assert response.status_code in (
        301,
        302,
        307,
        308,
    )


def test_get_crawl_trailing_slash_redirects_home(
    client: FlaskClient,
) -> None:
    response = client.get("/crawl/")

    assert response.status_code in (
        301,
        302,
        307,
        308,
    )


def test_invalid_username_returns_400_json(
    client: FlaskClient,
) -> None:
    response = client.post(
        "/crawl",
        data={
            "username": "",
            "max_items": "5",
        },
    )

    assert response.status_code == 400
    assert response.is_json

    payload = response.get_json()

    assert payload is not None

    assert payload["error"] == "invalid_username"


def test_non_numeric_max_items_returns_400(
    client: FlaskClient,
) -> None:
    response = client.post(
        "/crawl",
        data={
            "username": "test",
            "max_items": "hello",
        },
    )

    assert response.status_code == 400


def test_zero_max_items_returns_400(
    client: FlaskClient,
) -> None:
    response = client.post(
        "/crawl",
        data={
            "username": "test",
            "max_items": "0",
        },
    )

    assert response.status_code == 400


def test_negative_max_items_returns_400(
    client: FlaskClient,
) -> None:
    response = client.post(
        "/crawl",
        data={
            "username": "test",
            "max_items": "-100",
        },
    )

    assert response.status_code == 400


def test_too_large_max_items_returns_400(
    client: FlaskClient,
) -> None:
    response = client.post(
        "/crawl",
        data={
            "username": "test",
            "max_items": "101",
        },
    )

    assert response.status_code == 400


def test_missing_route_has_html_error_page(
    client: FlaskClient,
) -> None:
    response = client.get("/something-that-does-not-exist")

    assert response.status_code == 404

    content_type = response.content_type

    assert "text/html" in content_type


def test_internal_error_is_handled_as_html(
    app: Flask,
) -> None:
    @app.get("/__test_error")
    def test_error() -> str:
        raise RuntimeError("intentional test error")

    client = app.test_client()

    response = client.get("/__test_error")

    assert response.status_code == 500

    html = response.get_data(as_text=True)

    assert "خطای داخلی برنامه" in html

    assert "intentional test error" not in html


def test_favicon_does_not_return_404(
    client: FlaskClient,
) -> None:
    response = client.get("/favicon.ico")

    assert response.status_code == 200
