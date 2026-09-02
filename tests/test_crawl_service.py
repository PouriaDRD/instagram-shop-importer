from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.crawler.instagram.dto import (
    InstagramAssetDTO,
    InstagramAssetType,
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
        biography="Test biography",
        profile_picture_url=None,
        followers_count=100,
        following_count=50,
        media_count=10,
        is_private=False,
        raw_payload={},
    )


def make_media(
    *,
    media_id: str = "media-1",
    shortcode: str = "TEST001",
) -> InstagramMediaDTO:
    return InstagramMediaDTO(
        media_id=media_id,
        shortcode=shortcode,
        media_type=InstagramMediaType.IMAGE,
        permalink=(f"https://www.instagram.com/p/" f"{shortcode}/"),
        caption="Test caption",
        thumbnail_url=("https://example.com/" "thumbnail.jpg"),
        published_at=datetime(
            2026,
            9,
            2,
            10,
            0,
            0,
            tzinfo=timezone.utc,
        ),
        like_count=10,
        comment_count=2,
        view_count=None,
        assets=(
            InstagramAssetDTO(
                external_id=(f"{media_id}-asset-1"),
                asset_type=(InstagramAssetType.IMAGE),
                source_url=("https://example.com/" "image.jpg"),
                position=0,
                width=1080,
                height=1080,
                duration_seconds=None,
                metadata={},
            ),
        ),
        raw_payload={},
    )


class FakeProvider:
    def __init__(
        self,
        *,
        should_fail: bool = False,
    ) -> None:
        self.should_fail = should_fail

        self.profile_requested = False
        self.media_requested = False

        self.requested_username: str | None = None
        self.requested_max_items: int | None = None

    def fetch_profile(
        self,
        *,
        username: str,
    ) -> InstagramProfileDTO:
        self.profile_requested = True
        self.requested_username = username

        if self.should_fail:
            raise RuntimeError("provider failed")

        return make_profile(username=username)

    def fetch_media(
        self,
        *,
        username: str,
        max_items: int | None = None,
    ) -> tuple[InstagramMediaDTO, ...]:
        self.media_requested = True

        self.requested_username = username
        self.requested_max_items = max_items

        if self.should_fail:
            raise RuntimeError("provider failed")

        return (
            make_media(
                media_id="media-1",
                shortcode="TEST001",
            ),
            make_media(
                media_id="media-2",
                shortcode="TEST002",
            ),
        )


class TrackingRepository(CrawlSessionRepository):
    def __init__(self) -> None:
        self.session = CrawlSession(
            username="testshop",
            status="pending",
        )

        self.session.id = "session-1"

        self.running_called = False
        self.profile_called = False
        self.media_called = False
        self.completed_called = False
        self.failed_called = False

        self.saved_profile: InstagramProfileDTO | None = None

        self.saved_media: tuple[
            InstagramMediaDTO,
            ...,
        ] = ()

        self.error_message: str | None = None

    def create(
        self,
        *,
        username: str,
    ) -> CrawlSession:
        self.session.username = username
        self.session.status = "pending"

        return self.session

    def get(
        self,
        *,
        session_id: str,
    ) -> CrawlSession | None:
        if session_id != self.session.id:
            return None

        return self.session

    def mark_running(
        self,
        *,
        session: CrawlSession,
    ) -> None:
        self.running_called = True

        session.status = "running"

    def save_profile(
        self,
        *,
        session: CrawlSession,
        profile: InstagramProfileDTO,
    ) -> None:
        self.profile_called = True
        self.saved_profile = profile

        session.username = profile.username
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
        media_items: tuple[
            InstagramMediaDTO,
            ...,
        ],
    ) -> None:
        self.media_called = True
        self.saved_media = media_items

        session.crawled_media_count = len(media_items)

    def mark_completed(
        self,
        *,
        session: CrawlSession,
    ) -> None:
        self.completed_called = True

        session.status = "completed"

    def mark_failed(
        self,
        *,
        session: CrawlSession,
        error_message: str,
    ) -> None:
        self.failed_called = True

        self.error_message = error_message

        session.status = "failed"


def test_fake_provider_matches_protocol() -> None:
    provider = FakeProvider()

    profile = provider.fetch_profile(username="testshop")

    media = provider.fetch_media(
        username="testshop",
        max_items=5,
    )

    assert isinstance(
        profile,
        InstagramProfileDTO,
    )

    assert all(
        isinstance(
            item,
            InstagramMediaDTO,
        )
        for item in media
    )


def test_create_session_normalizes_username() -> None:
    repository = TrackingRepository()
    provider = FakeProvider()

    service = CrawlService(
        provider=provider,
        repository=repository,
    )

    session = service.create_session(
        username="  @testshop  ",
    )

    assert session.username == "testshop"


@pytest.mark.parametrize(
    "username",
    [
        "",
        " ",
        "@",
        "@@",
        "   @@   ",
    ],
)
def test_create_session_rejects_empty_username(
    username: str,
) -> None:
    repository = TrackingRepository()

    service = CrawlService(
        provider=FakeProvider(),
        repository=repository,
    )

    with pytest.raises(ValueError):
        service.create_session(username=username)


def test_successful_crawl_calls_all_steps() -> None:
    repository = TrackingRepository()
    provider = FakeProvider()

    service = CrawlService(
        provider=provider,
        repository=repository,
    )

    service.run(
        session_id="session-1",
        max_items=5,
    )

    assert repository.running_called
    assert repository.profile_called
    assert repository.media_called
    assert repository.completed_called

    assert not repository.failed_called

    assert provider.profile_requested
    assert provider.media_requested

    assert provider.requested_username == "testshop"

    assert provider.requested_max_items == 5

    assert repository.session.status == "completed"

    assert repository.session.crawled_media_count == 2

    assert len(repository.saved_media) == 2


def test_profile_is_saved_before_media() -> None:
    repository = TrackingRepository()
    provider = FakeProvider()

    service = CrawlService(
        provider=provider,
        repository=repository,
    )

    service.run(
        session_id="session-1",
        max_items=2,
    )

    assert repository.saved_profile is not None

    assert repository.saved_profile.username == "testshop"

    assert repository.session.full_name == "Test Shop"

    assert repository.session.followers_count == 100


def test_max_items_is_forwarded_to_provider() -> None:
    repository = TrackingRepository()
    provider = FakeProvider()

    service = CrawlService(
        provider=provider,
        repository=repository,
    )

    service.run(
        session_id="session-1",
        max_items=37,
    )

    assert provider.requested_max_items == 37


def test_none_max_items_is_forwarded() -> None:
    repository = TrackingRepository()
    provider = FakeProvider()

    service = CrawlService(
        provider=provider,
        repository=repository,
    )

    service.run(
        session_id="session-1",
        max_items=None,
    )

    assert provider.requested_max_items is None


def test_provider_failure_is_marked_failed() -> None:
    repository = TrackingRepository()

    provider = FakeProvider(
        should_fail=True,
    )

    service = CrawlService(
        provider=provider,
        repository=repository,
    )

    service.run(
        session_id="session-1",
        max_items=5,
    )

    assert repository.running_called
    assert repository.failed_called

    assert not repository.completed_called
    assert not repository.media_called

    assert repository.session.status == "failed"

    assert repository.error_message == "provider failed"


def test_unknown_session_fails_cleanly() -> None:
    repository = TrackingRepository()

    service = CrawlService(
        provider=FakeProvider(),
        repository=repository,
    )

    with pytest.raises(
        ValueError,
        match="does not exist",
    ):
        service.run(session_id="does-not-exist")


def test_unknown_session_does_not_call_provider() -> None:
    repository = TrackingRepository()
    provider = FakeProvider()

    service = CrawlService(
        provider=provider,
        repository=repository,
    )

    with pytest.raises(ValueError):
        service.run(session_id="missing")

    assert not provider.profile_requested
    assert not provider.media_requested

    assert not repository.running_called
    assert not repository.completed_called
    assert not repository.failed_called


def test_completed_session_contains_expected_media_count() -> None:
    repository = TrackingRepository()

    service = CrawlService(
        provider=FakeProvider(),
        repository=repository,
    )

    service.run(
        session_id="session-1",
        max_items=2,
    )

    assert repository.session.crawled_media_count == 2

    assert repository.session.status == "completed"
