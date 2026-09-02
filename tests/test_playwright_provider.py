from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from app.common.exceptions import (
    InstagramAuthenticationRequiredError,
    InstagramFetchTimeoutError,
    InstagramMediaFetchError,
    InstagramPrivateProfileError,
    InstagramProfileNotFoundError,
    InstagramProfileUnavailableError,
    InstagramProviderError,
    InstagramRateLimitedError,
)
from app.crawler.instagram.dto import (
    InstagramAssetType,
    InstagramMediaType,
)
from app.crawler.instagram.playwright_provider import (
    INSTAGRAM_BASE_URL,
    PlaywrightInstagramProvider,
)


@pytest.fixture
def provider() -> PlaywrightInstagramProvider:
    return PlaywrightInstagramProvider(
        headless=True,
        timeout_ms=5_000,
    )


def make_page(
    *,
    body: str = "",
    media_count: int = 0,
) -> MagicMock:
    page = MagicMock()

    body_locator = MagicMock()
    body_locator.inner_text.return_value = body

    media_locator = MagicMock()
    media_locator.count.return_value = media_count

    def locator(selector: str) -> MagicMock:
        if selector == "body":
            return body_locator

        if 'a[href*="/p/"]' in selector or 'a[href*="/reel/"]' in selector:
            return media_locator

        result = MagicMock()
        result.count.return_value = 0
        return result

    page.locator.side_effect = locator

    return page


def test_provider_rejects_invalid_timeout() -> None:
    with pytest.raises(
        ValueError,
        match="timeout must be positive",
    ):
        PlaywrightInstagramProvider(
            timeout_ms=0,
        )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("mahtabbeauty", "mahtabbeauty"),
        ("@mahtabbeauty", "mahtabbeauty"),
        ("  @mahtabbeauty  ", "mahtabbeauty"),
        (
            "https://www.instagram.com/mahtabbeauty/",
            "mahtabbeauty",
        ),
        (
            "http://instagram.com/mahtabbeauty/",
            "mahtabbeauty",
        ),
        (
            "instagram.com/mahtabbeauty/",
            "mahtabbeauty",
        ),
        (
            "www.instagram.com/mahtabbeauty/",
            "mahtabbeauty",
        ),
    ],
)
def test_username_normalization(
    provider: PlaywrightInstagramProvider,
    raw: str,
    expected: str,
) -> None:
    assert provider._normalize_username(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        " ",
        "@",
        "https://www.instagram.com/",
        "instagram.com/",
    ],
)
def test_invalid_username_is_rejected(
    provider: PlaywrightInstagramProvider,
    raw: str,
) -> None:
    with pytest.raises(ValueError):
        provider._normalize_username(raw)


def test_profile_not_found_is_detected(
    provider: PlaywrightInstagramProvider,
) -> None:
    page = make_page(
        body="Sorry, this page isn't available.",
    )

    with pytest.raises(
        InstagramProfileNotFoundError,
    ):
        provider._validate_profile_page(
            page=page,
            username="missing_shop",
            status_code=404,
        )


def test_private_profile_is_detected(
    provider: PlaywrightInstagramProvider,
) -> None:
    page = make_page(
        body="This account is private",
    )

    with pytest.raises(
        InstagramPrivateProfileError,
    ):
        provider._validate_profile_page(
            page=page,
            username="private_shop",
            status_code=200,
        )


def test_authentication_wall_is_detected(
    provider: PlaywrightInstagramProvider,
) -> None:
    page = make_page(
        body="Log in to Instagram",
        media_count=0,
    )

    with pytest.raises(
        InstagramAuthenticationRequiredError,
    ):
        provider._validate_profile_page(
            page=page,
            username="shop",
            status_code=200,
        )


def test_authentication_text_does_not_fail_when_profile_has_content(
    provider: PlaywrightInstagramProvider,
) -> None:
    page = make_page(
        body="Log in to Instagram",
        media_count=3,
    )

    provider._validate_profile_page(
        page=page,
        username="shop",
        status_code=200,
    )


def test_rate_limit_is_detected(
    provider: PlaywrightInstagramProvider,
) -> None:
    page = make_page()

    with pytest.raises(
        InstagramRateLimitedError,
    ):
        provider._validate_profile_page(
            page=page,
            username="shop",
            status_code=429,
        )


@pytest.mark.parametrize(
    "body",
    [
        "Something went wrong",
        "Please try again later",
    ],
)
def test_profile_unavailable_is_detected(
    provider: PlaywrightInstagramProvider,
    body: str,
) -> None:
    page = make_page(
        body=body,
    )

    with pytest.raises(
        InstagramProfileUnavailableError,
    ):
        provider._validate_profile_page(
            page=page,
            username="shop",
            status_code=200,
        )


def test_json_parser_accepts_valid_object(
    provider: PlaywrightInstagramProvider,
) -> None:
    result = provider._parse_json_script('{"code":"ABC123"}')

    assert result == {
        "code": "ABC123",
    }


@pytest.mark.parametrize(
    "value",
    [
        "",
        "hello",
        "{broken json",
        "<script>{}</script>",
    ],
)
def test_invalid_json_never_crashes(
    provider: PlaywrightInstagramProvider,
    value: str,
) -> None:
    assert provider._parse_json_script(value) is None


def test_media_url_normalization(
    provider: PlaywrightInstagramProvider,
) -> None:
    assert provider._normalize_media_url("/p/ABC123/?img_index=1") == (
        f"{INSTAGRAM_BASE_URL}/" "p/ABC123/"
    )

    assert provider._normalize_media_url("https://www.instagram.com/reel/XYZ789/") == (
        f"{INSTAGRAM_BASE_URL}/" "reel/XYZ789/"
    )


@pytest.mark.parametrize(
    "value",
    [
        "/",
        "/accounts/login/",
        "/explore/",
        "/p/",
        "",
    ],
)
def test_invalid_media_urls_are_ignored(
    provider: PlaywrightInstagramProvider,
    value: str,
) -> None:
    assert provider._normalize_media_url(value) is None


def test_shortcode_from_post_url(
    provider: PlaywrightInstagramProvider,
) -> None:
    assert (
        provider._shortcode_from_url("https://www.instagram.com/p/ABC123/") == "ABC123"
    )


def test_shortcode_from_reel_url(
    provider: PlaywrightInstagramProvider,
) -> None:
    assert (
        provider._shortcode_from_url("https://www.instagram.com/reel/XYZ789/")
        == "XYZ789"
    )


def test_invalid_shortcode_url_fails_cleanly(
    provider: PlaywrightInstagramProvider,
) -> None:
    with pytest.raises(
        InstagramMediaFetchError,
    ):
        provider._shortcode_from_url("https://www.instagram.com/explore/")


def test_duplicate_media_links_are_removed(
    provider: PlaywrightInstagramProvider,
) -> None:
    page = MagicMock()

    anchors = MagicMock()
    anchors.count.return_value = 4

    hrefs = [
        "/p/AAA/",
        "/p/AAA/",
        "/reel/BBB/",
        "/reel/BBB/?something=1",
    ]

    anchors.nth.side_effect = lambda index: MagicMock(
        get_attribute=MagicMock(return_value=hrefs[index])
    )

    page.locator.return_value = anchors

    result: list[str] = []
    seen: set[str] = set()

    provider._collect_media_links(
        page=page,
        result=result,
        seen=seen,
    )

    assert result == [
        ("https://www.instagram.com/" "p/AAA/"),
        ("https://www.instagram.com/" "reel/BBB/"),
    ]


def test_image_media_type_detection(
    provider: PlaywrightInstagramProvider,
) -> None:
    media_type = provider._detect_media_type(
        payload={
            "media_type": 1,
        },
        media_url=("https://www.instagram.com/" "p/ABC/"),
    )

    assert media_type == InstagramMediaType.IMAGE


def test_video_media_type_detection(
    provider: PlaywrightInstagramProvider,
) -> None:
    media_type = provider._detect_media_type(
        payload={
            "media_type": 2,
        },
        media_url=("https://www.instagram.com/" "p/ABC/"),
    )

    assert media_type == InstagramMediaType.VIDEO


def test_reel_media_type_detection(
    provider: PlaywrightInstagramProvider,
) -> None:
    media_type = provider._detect_media_type(
        payload={
            "media_type": 2,
        },
        media_url=("https://www.instagram.com/" "reel/ABC/"),
    )

    assert media_type == InstagramMediaType.REEL


def test_carousel_media_type_detection(
    provider: PlaywrightInstagramProvider,
) -> None:
    media_type = provider._detect_media_type(
        payload={
            "media_type": 8,
            "carousel_media": [
                {
                    "pk": "1",
                }
            ],
        },
        media_url=("https://www.instagram.com/" "p/ABC/"),
    )

    assert media_type == InstagramMediaType.CAROUSEL


def test_incomplete_carousel_does_not_crash(
    provider: PlaywrightInstagramProvider,
) -> None:
    assets = provider._build_assets_from_payload(
        payload={
            "carousel_media": [
                None,
                "broken",
                {},
                {
                    "pk": "child1",
                    "media_type": 1,
                    "image_versions2": {
                        "candidates": [
                            {
                                "url": ("https://cdn.example.com/" "image.jpg"),
                                "width": 1000,
                                "height": 1200,
                            }
                        ]
                    },
                },
            ]
        }
    )

    assert len(assets) == 1
    assert assets[0].asset_type == InstagramAssetType.IMAGE


def test_reel_without_video_url_does_not_crash(
    provider: PlaywrightInstagramProvider,
) -> None:
    assets = provider._build_assets_from_payload(
        payload={
            "pk": "123",
            "media_type": 2,
            "image_versions2": {
                "candidates": [
                    {
                        "url": ("https://cdn.example.com/" "thumb.jpg"),
                        "width": 1080,
                        "height": 1920,
                    }
                ]
            },
            "video_versions": [],
        }
    )

    assert len(assets) == 1

    assert assets[0].asset_type == InstagramAssetType.THUMBNAIL


def test_duplicate_assets_are_removed(
    provider: PlaywrightInstagramProvider,
) -> None:
    payload = {
        "carousel_media": [
            {
                "pk": "1",
                "media_type": 1,
                "image_versions2": {
                    "candidates": [
                        {
                            "url": ("https://cdn.example.com/" "same.jpg"),
                            "width": 1000,
                            "height": 1000,
                        },
                        {
                            "url": ("https://cdn.example.com/" "same.jpg"),
                            "width": 1000,
                            "height": 1000,
                        },
                    ]
                },
            }
        ]
    }

    assets = provider._build_assets_from_payload(
        payload=payload,
    )

    assert len(assets) == 1


def test_invalid_unix_timestamp_is_safe(
    provider: PlaywrightInstagramProvider,
) -> None:
    assert provider._datetime_from_unix(None) is None

    assert provider._datetime_from_unix(True) is None

    assert provider._datetime_from_unix("broken") is None

    assert provider._datetime_from_unix(10**30) is None


def test_valid_unix_timestamp_is_utc(
    provider: PlaywrightInstagramProvider,
) -> None:
    result = provider._datetime_from_unix(1_756_812_217)

    assert isinstance(
        result,
        datetime,
    )

    assert result.tzinfo == timezone.utc


def test_profile_timeout_is_translated(
    provider: PlaywrightInstagramProvider,
) -> None:
    fake_context = MagicMock()

    page = MagicMock()
    fake_context.new_page.return_value = page

    @contextmanager
    def fake_browser_context() -> Iterator[MagicMock]:
        yield fake_context

    with (
        patch.object(
            provider,
            "_browser_context",
            fake_browser_context,
        ),
        patch.object(
            provider,
            "_fetch_profile_from_page",
            side_effect=PlaywrightTimeoutError("timeout"),
        ),
    ):
        with pytest.raises(
            InstagramFetchTimeoutError,
        ):
            provider.fetch_profile(
                username="shop",
            )


@pytest.mark.parametrize(
    "error",
    [
        InstagramProfileNotFoundError("missing"),
        InstagramPrivateProfileError("private"),
        InstagramAuthenticationRequiredError("auth"),
        InstagramRateLimitedError("rate limited"),
        InstagramProfileUnavailableError("unavailable"),
    ],
)
def test_specific_profile_errors_are_not_hidden(
    provider: PlaywrightInstagramProvider,
    error: Exception,
) -> None:
    fake_context = MagicMock()

    fake_context.new_page.return_value = MagicMock()

    @contextmanager
    def fake_browser_context() -> Iterator[MagicMock]:
        yield fake_context

    with (
        patch.object(
            provider,
            "_browser_context",
            fake_browser_context,
        ),
        patch.object(
            provider,
            "_fetch_profile_from_page",
            side_effect=error,
        ),
    ):
        with pytest.raises(
            error.__class__,
        ):
            provider.fetch_profile(
                username="shop",
            )


def test_browser_initialization_failure_is_wrapped(
    provider: PlaywrightInstagramProvider,
) -> None:
    with patch(
        ("app.crawler.instagram." "playwright_provider.sync_playwright")
    ) as mocked:
        mocked.return_value.start.side_effect = RuntimeError("browser exploded")

        with pytest.raises(
            InstagramProviderError,
        ):
            with provider._browser_context():
                raise AssertionError("must not enter")


def test_cleanup_failure_does_not_hide_original_error(
    provider: PlaywrightInstagramProvider,
) -> None:
    playwright = MagicMock()
    browser = MagicMock()
    context = MagicMock()

    playwright.chromium.launch.return_value = browser

    browser.new_context.return_value = context

    context.close.side_effect = RuntimeError("context close failed")

    browser.close.side_effect = RuntimeError("browser close failed")

    playwright.stop.side_effect = RuntimeError("playwright stop failed")

    with patch(
        ("app.crawler.instagram." "playwright_provider.sync_playwright")
    ) as mocked:
        mocked.return_value.start.return_value = playwright

        with pytest.raises(
            InstagramPrivateProfileError,
            match="private",
        ):
            with provider._browser_context():
                raise InstagramPrivateProfileError("private")
