from __future__ import annotations

import os
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)

import pytest
from flask import Flask

from app.extensions import db
from app.repositories import (
    CrawlSessionRepository,
)

SEQUENTIAL_REQUESTS = int(
    os.getenv(
        "STRESS_REQUESTS",
        "1500",
    )
)

CONCURRENT_REQUESTS = int(
    os.getenv(
        "STRESS_CONCURRENT_REQUESTS",
        "500",
    )
)

WORKERS = int(
    os.getenv(
        "STRESS_WORKERS",
        "20",
    )
)


def create_sessions(
    app: Flask,
    *,
    count: int,
) -> list[str]:
    ids: list[str] = []

    with app.app_context():
        repository = CrawlSessionRepository()

        for index in range(count):
            session = repository.create(username=(f"stress_shop_{index}"))

            if index % 4 == 0:
                session.status = "completed"

            elif index % 4 == 1:
                session.status = "pending"

            elif index % 4 == 2:
                session.status = "running"

            else:
                session.status = "failed"

                session.error_message = "Synthetic failure"

            db.session.commit()

            ids.append(session.id)

    return ids


@pytest.mark.stress
def test_home_page_1500_times(
    app: Flask,
) -> None:
    client = app.test_client()

    for _ in range(SEQUENTIAL_REQUESTS):
        response = client.get("/")

        assert response.status_code == 200


@pytest.mark.stress
def test_crawl_list_1000_times(
    app: Flask,
) -> None:
    create_sessions(
        app,
        count=50,
    )

    client = app.test_client()

    for _ in range(SEQUENTIAL_REQUESTS):
        response = client.get("/crawls")

        assert response.status_code == 200


@pytest.mark.stress
def test_every_session_state_repeatedly(
    app: Flask,
) -> None:
    session_ids = create_sessions(
        app,
        count=100,
    )

    client = app.test_client()

    for _ in range(10):
        for session_id in session_ids:
            response = client.get(f"/crawl/{session_id}")

            assert response.status_code == 200


@pytest.mark.stress
def test_concurrent_home_requests(
    app: Flask,
) -> None:
    def request_once() -> int:
        with app.test_client() as client:
            response = client.get("/")
            return response.status_code

    with ThreadPoolExecutor(
        max_workers=WORKERS,
    ) as executor:
        futures = [executor.submit(request_once) for _ in range(CONCURRENT_REQUESTS)]

        statuses = [future.result() for future in as_completed(futures)]

    assert statuses

    assert all(status == 200 for status in statuses)


@pytest.mark.stress
def test_concurrent_session_list_requests(
    app: Flask,
) -> None:
    create_sessions(
        app,
        count=75,
    )

    def request_once() -> int:
        with app.test_client() as client:
            response = client.get("/crawls")

            return response.status_code

    with ThreadPoolExecutor(
        max_workers=WORKERS,
    ) as executor:
        futures = [executor.submit(request_once) for _ in range(CONCURRENT_REQUESTS)]

        results = [future.result() for future in as_completed(futures)]

    assert all(status == 200 for status in results)


@pytest.mark.stress
def test_concurrent_detail_requests(
    app: Flask,
) -> None:
    session_ids = create_sessions(
        app,
        count=25,
    )

    def request_once(
        session_id: str,
    ) -> int:
        with app.test_client() as client:
            response = client.get(f"/crawl/{session_id}")

            return response.status_code

    tasks: list[str] = []

    while len(tasks) < (CONCURRENT_REQUESTS):
        tasks.extend(session_ids)

    tasks = tasks[:CONCURRENT_REQUESTS]

    with ThreadPoolExecutor(
        max_workers=WORKERS,
    ) as executor:
        futures = [
            executor.submit(
                request_once,
                session_id,
            )
            for session_id in tasks
        ]

        statuses = [future.result() for future in as_completed(futures)]

    assert all(status == 200 for status in statuses)


@pytest.mark.stress
def test_invalid_requests_never_return_500(
    app: Flask,
) -> None:
    client = app.test_client()

    bad_payloads = [
        {},
        {
            "username": "",
        },
        {
            "username": "@",
        },
        {
            "username": "test",
            "max_items": "abc",
        },
        {
            "username": "test",
            "max_items": "-1",
        },
        {
            "username": "test",
            "max_items": "0",
        },
        {
            "username": "test",
            "max_items": "101",
        },
        {
            "username": "test",
            "max_items": "999999999999",
        },
    ]

    for _ in range(100):
        for payload in bad_payloads:
            response = client.post(
                "/crawl",
                data=payload,
            )

            assert response.status_code != 500


@pytest.mark.stress
def test_random_missing_session_ids_never_500(
    app: Flask,
) -> None:
    client = app.test_client()

    bad_ids = [
        "",
        "x",
        "null",
        "none",
        "undefined",
        "0",
        "-1",
        "%%%%",
        "not-a-uuid",
        "a" * 500,
    ]

    for _ in range(100):
        for value in bad_ids:
            if not value:
                url = "/crawl/"
            else:
                url = f"/crawl/{value}"

            response = client.get(url)

            assert response.status_code != 500
