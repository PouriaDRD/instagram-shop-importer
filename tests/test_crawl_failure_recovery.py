from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.crawler.base import InstagramProvider
from app.crawler.instagram.dto import (
    InstagramMediaDTO,
    InstagramMediaType,
    InstagramProfileDTO,
)
from app.models import CrawlSession
from app.repositories import CrawlSessionRepository
from app.services import CrawlService


def make_profile(
    *,
    username: str = "testshop",
) -> InstagramProfileDTO:
    return InstagramProfileDTO(
        username=username,
        full_name="Test Shop",
        biography="Test bio",
        profile_picture_url=None,
        followers_count=100,
        following_count=20,
        media_count=1,
        is_private=False,
        raw_payload={},
    )


def make_media() -> InstagramMediaDTO:
    return InstagramMediaDTO(
        media_id="media-1",
        shortcode="ABC123",
        media_type=InstagramMediaType.IMAGE,
        permalink=("https://www.instagram.com/" "p/ABC123/"),
        caption="Test",
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
        comment_count=2,
        view_count=None,
        assets=(),
        raw_payload={},
    )


class SuccessfulProvider:
    def fetch_profile(
        self,
        *,
        username: str,
    ) -> InstagramProfileDTO:
        return make_profile(
            username=username,
        )

    def fetch_media(
        self,
        *,
        username: str,
        max_items: int | None = None,
    ) -> tuple[InstagramMediaDTO, ...]:
        del username
        del max_items

        return (make_media(),)


class FailingProfileProvider:
    def fetch_profile(
        self,
        *,
        username: str,
    ) -> InstagramProfileDTO:
        raise RuntimeError(f"profile failure: {username}")

    def fetch_media(
        self,
        *,
        username: str,
        max_items: int | None = None,
    ) -> tuple[InstagramMediaDTO, ...]:
        del username
        del max_items

        raise AssertionError("fetch_media must not run")


class FailingMediaProvider:
    def fetch_profile(
        self,
        *,
        username: str,
    ) -> InstagramProfileDTO:
        return make_profile(
            username=username,
        )

    def fetch_media(
        self,
        *,
        username: str,
        max_items: int | None = None,
    ) -> tuple[InstagramMediaDTO, ...]:
        del username
        del max_items

        raise RuntimeError("media failure")


class FailureInjectionRepository(
    CrawlSessionRepository,
):
    def __init__(
        self,
        *,
        fail_on: str | None = None,
    ) -> None:
        super().__init__()

        self.fail_on = fail_on
        self.mark_failed_calls = 0

    def mark_running(
        self,
        *,
        session: CrawlSession,
    ) -> None:
        if self.fail_on == "mark_running":
            raise RuntimeError("mark_running failed")

        super().mark_running(
            session=session,
        )

    def save_profile(
        self,
        *,
        session: CrawlSession,
        profile: InstagramProfileDTO,
    ) -> None:
        if self.fail_on == "save_profile":
            raise RuntimeError("save_profile failed")

        super().save_profile(
            session=session,
            profile=profile,
        )

    def replace_media(
        self,
        *,
        session: CrawlSession,
        media_items: tuple[InstagramMediaDTO, ...],
    ) -> None:
        if self.fail_on == "replace_media":
            raise RuntimeError("replace_media failed")

        super().replace_media(
            session=session,
            media_items=media_items,
        )

    def mark_completed(
        self,
        *,
        session: CrawlSession,
    ) -> None:
        if self.fail_on == "mark_completed":
            raise RuntimeError("mark_completed failed")

        super().mark_completed(
            session=session,
        )

    def mark_failed(
        self,
        *,
        session: CrawlSession,
        error_message: str,
    ) -> None:
        self.mark_failed_calls += 1

        if self.fail_on == "mark_failed":
            raise RuntimeError("mark_failed failed")

        super().mark_failed(
            session=session,
            error_message=error_message,
        )


def create_session(
    repository: CrawlSessionRepository,
    *,
    username: str = "testshop",
) -> CrawlSession:
    return repository.create(
        username=username,
    )


def reload_session(
    repository: CrawlSessionRepository,
    *,
    session_id: str,
) -> CrawlSession:
    result = repository.get(
        session_id=session_id,
    )

    assert result is not None

    return result


def test_successful_provider_matches_protocol() -> None:
    provider: InstagramProvider = SuccessfulProvider()

    assert provider is not None


def test_profile_failure_marks_session_failed(
    app,
) -> None:
    with app.app_context():
        repository = FailureInjectionRepository()

        session = create_session(
            repository,
        )

        service = CrawlService(
            provider=FailingProfileProvider(),
            repository=repository,
        )

        service.run(
            session_id=session.id,
        )

        result = reload_session(
            repository,
            session_id=session.id,
        )

        assert result.status == "failed"

        assert result.error_message is not None

        assert "profile failure" in result.error_message


def test_media_failure_marks_session_failed(
    app,
) -> None:
    with app.app_context():
        repository = FailureInjectionRepository()

        session = create_session(
            repository,
        )

        service = CrawlService(
            provider=FailingMediaProvider(),
            repository=repository,
        )

        service.run(
            session_id=session.id,
        )

        result = reload_session(
            repository,
            session_id=session.id,
        )

        assert result.status == "failed"

        assert result.error_message is not None

        assert "media failure" in result.error_message


@pytest.mark.parametrize(
    "failure_point",
    [
        "mark_running",
        "save_profile",
        "replace_media",
        "mark_completed",
    ],
)
def test_database_failure_attempts_failed_state(
    app,
    failure_point: str,
) -> None:
    with app.app_context():
        repository = FailureInjectionRepository(
            fail_on=failure_point,
        )

        session = create_session(
            repository,
        )

        service = CrawlService(
            provider=SuccessfulProvider(),
            repository=repository,
        )

        service.run(
            session_id=session.id,
        )

        assert repository.mark_failed_calls == 1


def test_mark_failed_failure_does_not_escape_service(
    app,
) -> None:
    with app.app_context():
        repository = FailureInjectionRepository(
            fail_on="mark_failed",
        )

        session = create_session(
            repository,
        )

        service = CrawlService(
            provider=FailingProfileProvider(),
            repository=repository,
        )

        service.run(
            session_id=session.id,
        )

        assert repository.mark_failed_calls == 1


def test_unknown_session_still_raises_value_error(
    app,
) -> None:
    with app.app_context():
        repository = FailureInjectionRepository()

        service = CrawlService(
            provider=SuccessfulProvider(),
            repository=repository,
        )

        with pytest.raises(
            ValueError,
            match=("Crawl session " "does not exist"),
        ):
            service.run(
                session_id="missing-id",
            )


def test_long_error_message_is_truncated(
    app,
) -> None:
    class LongErrorProvider:
        def fetch_profile(
            self,
            *,
            username: str,
        ) -> InstagramProfileDTO:
            del username

            raise RuntimeError("x" * 10_000)

        def fetch_media(
            self,
            *,
            username: str,
            max_items: int | None = None,
        ) -> tuple[InstagramMediaDTO, ...]:
            del username
            del max_items

            return ()

    with app.app_context():
        repository = FailureInjectionRepository()

        session = create_session(
            repository,
        )

        service = CrawlService(
            provider=LongErrorProvider(),
            repository=repository,
        )

        service.run(
            session_id=session.id,
        )

        result = reload_session(
            repository,
            session_id=session.id,
        )

        assert result.error_message is not None

        assert len(result.error_message) <= 2000


def test_empty_exception_message_uses_class_name(
    app,
) -> None:
    class EmptyErrorProvider:
        def fetch_profile(
            self,
            *,
            username: str,
        ) -> InstagramProfileDTO:
            del username

            raise RuntimeError()

        def fetch_media(
            self,
            *,
            username: str,
            max_items: int | None = None,
        ) -> tuple[InstagramMediaDTO, ...]:
            del username
            del max_items

            return ()

    with app.app_context():
        repository = FailureInjectionRepository()

        session = create_session(
            repository,
        )

        service = CrawlService(
            provider=EmptyErrorProvider(),
            repository=repository,
        )

        service.run(
            session_id=session.id,
        )

        result = reload_session(
            repository,
            session_id=session.id,
        )

        assert result.error_message == "RuntimeError"
