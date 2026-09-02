from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from datetime import datetime, timezone

import pytest

from app.crawler.instagram.dto import (
    InstagramMediaDTO,
    InstagramMediaType,
    InstagramProfileDTO,
)
from app.models import CrawlSession
from app.repositories import CrawlSessionRepository
from app.services import CrawlService

CRAWL_COUNT = int(
    os.getenv(
        "CRAWLER_STRESS_COUNT",
        "300",
    )
)

CRAWL_WORKERS = int(
    os.getenv(
        "CRAWLER_STRESS_WORKERS",
        "20",
    )
)


class ConcurrentProvider:
    def fetch_profile(
        self,
        *,
        username: str,
    ) -> InstagramProfileDTO:
        return InstagramProfileDTO(
            username=username,
            full_name=(f"Shop {username}"),
            biography=(f"Biography for {username}"),
            profile_picture_url=None,
            followers_count=100,
            following_count=20,
            media_count=1,
            is_private=False,
            raw_payload={
                "username": username,
            },
        )

    def fetch_media(
        self,
        *,
        username: str,
        max_items: int | None = None,
    ) -> tuple[InstagramMediaDTO, ...]:
        if max_items is not None and max_items <= 0:
            return ()

        return (
            InstagramMediaDTO(
                media_id=(f"media-{username}"),
                shortcode=(f"code-{username}"),
                media_type=(InstagramMediaType.IMAGE),
                permalink=("https://www.instagram.com/" f"p/{username}/"),
                caption=(f"caption-{username}"),
                thumbnail_url=None,
                published_at=datetime(
                    2026,
                    9,
                    2,
                    10,
                    0,
                    tzinfo=timezone.utc,
                ),
                like_count=10,
                comment_count=1,
                view_count=None,
                assets=(),
                raw_payload={
                    "username": username,
                },
            ),
        )


class ThreadSafeRepository(
    CrawlSessionRepository,
):
    def __init__(self) -> None:
        self._lock = threading.RLock()

        self._sessions: dict[
            str,
            CrawlSession,
        ] = {}

        self.media_owners: dict[
            str,
            tuple[str, ...],
        ] = {}

    def create(
        self,
        *,
        username: str,
    ) -> CrawlSession:
        with self._lock:
            session = CrawlSession(
                username=username,
                status="pending",
            )

            session.id = str(uuid.uuid4())

            session.crawled_media_count = 0
            session.error_message = None

            self._sessions[session.id] = session

            return session

    def get(
        self,
        *,
        session_id: str,
    ) -> CrawlSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def mark_running(
        self,
        *,
        session: CrawlSession,
    ) -> None:
        with self._lock:
            session.status = "running"

            session.started_at = datetime.now(timezone.utc)

    def save_profile(
        self,
        *,
        session: CrawlSession,
        profile: InstagramProfileDTO,
    ) -> None:
        with self._lock:
            session.full_name = profile.full_name

            session.biography = profile.biography

            session.profile_picture_url = profile.profile_picture_url

            session.followers_count = profile.followers_count

            session.following_count = profile.following_count

            session.instagram_media_count = profile.media_count

            session.is_private = profile.is_private

    def replace_media(
        self,
        *,
        session: CrawlSession,
        media_items: tuple[InstagramMediaDTO, ...],
    ) -> None:
        with self._lock:
            session.crawled_media_count = len(media_items)

            self.media_owners[session.id] = tuple(
                media.shortcode for media in media_items
            )

    def mark_completed(
        self,
        *,
        session: CrawlSession,
    ) -> None:
        with self._lock:
            session.status = "completed"

            session.completed_at = datetime.now(timezone.utc)

            session.error_message = None

    def mark_failed(
        self,
        *,
        session: CrawlSession,
        error_message: str,
    ) -> None:
        with self._lock:
            session.status = "failed"

            session.completed_at = datetime.now(timezone.utc)

            session.error_message = error_message

    def snapshot(
        self,
    ) -> tuple[CrawlSession, ...]:
        with self._lock:
            return tuple(self._sessions.values())


class MixedFailureProvider:
    def fetch_profile(
        self,
        *,
        username: str,
    ) -> InstagramProfileDTO:
        if username.endswith("_fail"):
            raise RuntimeError(f"forced-profile-failure:{username}")

        return ConcurrentProvider().fetch_profile(
            username=username,
        )

    def fetch_media(
        self,
        *,
        username: str,
        max_items: int | None = None,
    ) -> tuple[InstagramMediaDTO, ...]:
        return ConcurrentProvider().fetch_media(
            username=username,
            max_items=max_items,
        )


def run_one_crawl(
    *,
    repository: ThreadSafeRepository,
    provider: ConcurrentProvider,
    username: str,
) -> str:
    service = CrawlService(
        provider=provider,
        repository=repository,
    )

    session = service.create_session(
        username=username,
    )

    service.run(
        session_id=session.id,
        max_items=1,
    )

    return session.id


@pytest.mark.stress
def test_many_crawls_complete_without_state_leakage() -> None:
    repository = ThreadSafeRepository()

    provider = ConcurrentProvider()

    session_ids: list[str] = []

    with ThreadPoolExecutor(
        max_workers=CRAWL_WORKERS,
    ) as executor:
        futures = [
            executor.submit(
                run_one_crawl,
                repository=repository,
                provider=provider,
                username=f"shop_{index}",
            )
            for index in range(CRAWL_COUNT)
        ]

        for future in as_completed(futures):
            session_ids.append(future.result())

    assert len(session_ids) == CRAWL_COUNT

    assert len(set(session_ids)) == CRAWL_COUNT

    sessions = repository.snapshot()

    assert len(sessions) == CRAWL_COUNT

    for session in sessions:
        assert session.status == "completed"

        assert session.crawled_media_count == 1

        assert session.error_message is None

        shortcodes = repository.media_owners[session.id]

        assert shortcodes == (f"code-{session.username}",)


@pytest.mark.stress
def test_success_and_failure_crawls_do_not_affect_each_other() -> None:
    repository = ThreadSafeRepository()

    provider = MixedFailureProvider()

    session_ids: list[str] = []

    def job(
        index: int,
    ) -> str:
        service = CrawlService(
            provider=provider,
            repository=repository,
        )

        suffix = "_fail" if index % 5 == 0 else ""

        username = f"shop_{index}{suffix}"

        session = service.create_session(
            username=username,
        )

        service.run(
            session_id=session.id,
            max_items=1,
        )

        return session.id

    with ThreadPoolExecutor(
        max_workers=CRAWL_WORKERS,
    ) as executor:
        futures = [
            executor.submit(
                job,
                index,
            )
            for index in range(CRAWL_COUNT)
        ]

        for future in as_completed(futures):
            session_ids.append(future.result())

    assert len(session_ids) == CRAWL_COUNT

    sessions = repository.snapshot()

    completed = [session for session in sessions if session.status == "completed"]

    failed = [session for session in sessions if session.status == "failed"]

    expected_failed = len([index for index in range(CRAWL_COUNT) if index % 5 == 0])

    assert len(failed) == expected_failed

    assert len(completed) == (CRAWL_COUNT - expected_failed)

    for session in failed:
        assert session.error_message is not None

        assert "forced-profile-failure" in session.error_message

        assert session.crawled_media_count == 0

    for session in completed:
        assert session.error_message is None

        assert session.crawled_media_count == 1


@pytest.mark.stress
def test_repeated_crawls_for_same_username_remain_independent() -> None:
    repository = ThreadSafeRepository()

    provider = ConcurrentProvider()

    def job() -> str:
        return run_one_crawl(
            repository=repository,
            provider=provider,
            username="same_shop",
        )

    with ThreadPoolExecutor(
        max_workers=CRAWL_WORKERS,
    ) as executor:
        futures = [executor.submit(job) for _ in range(CRAWL_COUNT)]

        session_ids = [future.result() for future in as_completed(futures)]

    assert len(set(session_ids)) == CRAWL_COUNT

    sessions = repository.snapshot()

    assert all(session.username == "same_shop" for session in sessions)

    assert all(session.status == "completed" for session in sessions)


@pytest.mark.stress
def test_no_session_remains_running_after_mixed_load() -> None:
    repository = ThreadSafeRepository()

    provider = MixedFailureProvider()

    def job(
        index: int,
    ) -> None:
        service = CrawlService(
            provider=provider,
            repository=repository,
        )

        username = f"load_{index}"

        if index % 7 == 0:
            username += "_fail"

        session = service.create_session(
            username=username,
        )

        service.run(
            session_id=session.id,
            max_items=1,
        )

    with ThreadPoolExecutor(
        max_workers=CRAWL_WORKERS,
    ) as executor:
        futures = [
            executor.submit(
                job,
                index,
            )
            for index in range(CRAWL_COUNT)
        ]

        for future in as_completed(futures):
            future.result()

    sessions = repository.snapshot()

    assert not any(session.status == "running" for session in sessions)

    assert all(
        session.status
        in {
            "completed",
            "failed",
        }
        for session in sessions
    )
