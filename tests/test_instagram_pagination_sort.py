"""Regression coverage for infinite-scroll discovery and chronological ordering."""

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.crawler.instagram.dto import InstagramMediaDTO, InstagramMediaType
from app.crawler.instagram.playwright_provider import (
    INSTAGRAM_BASE_URL,
    PlaywrightInstagramProvider,
)


def make_media(shortcode: str, day: int | None) -> InstagramMediaDTO:
    return InstagramMediaDTO(
        media_id=shortcode,
        shortcode=shortcode,
        media_type=InstagramMediaType.IMAGE,
        permalink=f"{INSTAGRAM_BASE_URL}/p/{shortcode}/",
        published_at=(datetime(2026, 1, day, tzinfo=timezone.utc) if day else None),
    )


def profile_page(batches: list[list[str]]) -> tuple[MagicMock, object]:
    """Each scroll exposes a new grid batch, as happens on Instagram."""
    page = MagicMock()
    # Page.url is always a string in real Playwright; make the mock realistic
    # so cookie-consent navigation can safely inspect the visited address.
    page.url = f"{INSTAGRAM_BASE_URL}/shop/"
    index = [0]
    page.goto.return_value.status = 200
    # By default, the profile does not expose an expandable-post button.
    page.get_by_role.return_value.first.is_visible.return_value = False
    anchors = MagicMock()
    def locate(selector: str) -> MagicMock:
        if selector == "body":
            return body
        return anchors
    body = MagicMock()
    body.inner_text.return_value = "Profile"
    page.locator.side_effect = locate
    anchors.count.side_effect = lambda: len(batches[min(index[0],len(batches)-1)])
    anchors.nth.side_effect = lambda n: MagicMock(
        get_attribute=MagicMock(return_value=batches[min(index[0],len(batches)-1)][n]))
    def scroll(*, page: MagicMock) -> None:
        index[0] += 1
    return page, scroll


def test_pagination_goes_beyond_initial_twelve() -> None:
    provider = PlaywrightInstagramProvider(timeout_ms=5000)
    first = [f"/p/POST{i:03d}/" for i in range(12)]
    second = first + [f"/p/POST{i:03d}/" for i in range(12,25)]
    page, scroll = profile_page([first, second])
    provider._scroll_profile_media_grid = scroll
    urls = provider._discover_media_urls(page=page, username="shop", max_items=20)
    assert len(urls) == 20
    assert len(set(urls)) == 20
    assert urls[-1].endswith("POST019/")


def test_duplicate_post_reel_shortcodes_are_deduplicated() -> None:
    provider = PlaywrightInstagramProvider(timeout_ms=5000)
    page, _ = profile_page([["/p/A/", "/reel/A/", "/reel/B/?x=1"]])
    result = []
    seen = set()
    provider._collect_media_links(page=page, result=result, seen=seen)
    assert result == [f"{INSTAGRAM_BASE_URL}/p/A/", f"{INSTAGRAM_BASE_URL}/reel/B/"]


def test_chronological_sort_with_pinned_old_and_unknown_dates() -> None:
    provider = PlaywrightInstagramProvider(timeout_ms=5000)
    values = [make_media("PINNED", 1), make_media("LATEST", 15),
              make_media("MIDDLE", 10), make_media("UNKNOWN", None)]
    newest = sorted(values, key=lambda v: provider._media_chronological_key(
        media=v,sort_order="newest"))
    oldest = sorted(values, key=lambda v: provider._media_chronological_key(
        media=v,sort_order="oldest"))
    assert [x.shortcode for x in newest] == ["LATEST", "MIDDLE", "PINNED", "UNKNOWN"]
    assert [x.shortcode for x in oldest] == ["PINNED", "MIDDLE", "LATEST", "UNKNOWN"]


def test_oldest_requires_access_to_all_posts() -> None:
    provider = PlaywrightInstagramProvider(timeout_ms=5000)
    page = MagicMock()
    @contextmanager
    def context():
        yield MagicMock(new_page=MagicMock(return_value=page))
    provider._browser_context = context
    provider._discover_media_urls = lambda **kwargs: tuple(
        f"{INSTAGRAM_BASE_URL}/p/P{i}/" for i in range(12))
    with pytest.raises(Exception, match="Cannot guarantee"):
        provider.fetch_media(username="shop", max_items=5, sort_order="oldest",expected_media_count=100)


def test_fetch_media_selects_oldest_after_exhaustive_discovery() -> None:
    provider = PlaywrightInstagramProvider(timeout_ms=5000)
    @contextmanager
    def context():
        yield MagicMock(new_page=MagicMock())
    provider._browser_context = context
    provider._discover_media_urls = lambda **kwargs: tuple(
        f"{INSTAGRAM_BASE_URL}/p/P{i}/" for i in range(1,21))
    provider._fetch_media_detail = lambda **kw: make_media(
        kw["media_url"].split("/")[-2], int(kw["media_url"].split("/")[-2][1:]))
    result = provider.fetch_media(username="shop",max_items=4,sort_order="oldest",expected_media_count=20)
    assert len(result) == 4
    # The first 3 candidates were pinned in the grid; sorting finds the true oldest.
    assert [item.shortcode for item in result] == ["P1", "P2", "P3", "P17"]


def test_invalid_sort_order_is_rejected() -> None:
    provider = PlaywrightInstagramProvider(timeout_ms=5000)
    with pytest.raises(ValueError,match="sort order"):
        provider.fetch_media(username="shop", sort_order="random")


def test_incomplete_crawl_is_reported_not_silently_committed() -> None:
    provider = PlaywrightInstagramProvider(timeout_ms=5000)
    @contextmanager
    def context():
        yield MagicMock(new_page=MagicMock())
    provider._browser_context = context
    provider._discover_media_urls = lambda **kwargs: tuple(
        f"{INSTAGRAM_BASE_URL}/p/P{i}/" for i in range(12))
    provider._fetch_media_detail = lambda **kw: make_media(
        kw["media_url"].split("/")[-2], 1)
    with pytest.raises(Exception, match="only 12 of the requested 20"):
        provider.fetch_media(username="shop", max_items=20)


def test_click_show_more_posts_matches_provided_role_button() -> None:
    """Instagram uses a role=button div, NOT a native button or CSS class."""
    provider = PlaywrightInstagramProvider(timeout_ms=5000)
    page = MagicMock()
    button = page.get_by_role.return_value.first
    button.is_visible.return_value = True

    assert provider._click_show_more_posts(page=page, username="setayeshmasjedii")
    button.click.assert_called_once_with(timeout=5000)
    args, kwargs = page.get_by_role.call_args
    assert args == ("button",)
    assert kwargs["name"].search("Show more posts from setayeshmasjedii")
    assert kwargs["name"].search("Show more posts from otheruser") is None


def test_button_click_reveals_more_than_twelve_distinct_posts() -> None:
    """Scrolling alone exposes the same 12; the explicit button grows grid."""
    provider = PlaywrightInstagramProvider(timeout_ms=5000)
    first = [f"/p/POST{i:03d}/" for i in range(12)]
    expanded = first + [f"/p/POST{i:03d}/" for i in range(12, 36)]
    page, _ = profile_page([first, expanded])
    batch = [0]
    anchors = page.locator.return_value
    # Override the existing locator fixture with two sets of tiles; the
    # scroll is deliberately a no-op to reproduce the production failure.
    def locate(selector: str):
        if selector == "body":
            body = MagicMock()
            body.inner_text.return_value = "Profile"
            return body
        return anchors
    page.locator.side_effect = locate
    anchors.count.side_effect = lambda: len([first, expanded][batch[0]])
    anchors.nth.side_effect = lambda n: MagicMock(
        get_attribute=MagicMock(return_value=[first, expanded][batch[0]][n])
    )
    provider._scroll_profile_media_grid = lambda **kwargs: None

    button = page.get_by_role.return_value.first
    button.is_visible.side_effect = lambda: batch[0] == 0
    button.click.side_effect = lambda **kwargs: batch.__setitem__(0, 1)

    urls = provider._discover_media_urls(
        page=page, username="setayeshmasjedii", max_items=27
    )
    assert len(urls) == 27
    assert urls[-1].endswith("POST026/")
    assert len(set(urls)) == 27
    assert button.click.call_count == 1


def test_load_more_not_clicked_for_wrong_username() -> None:
    provider = PlaywrightInstagramProvider(timeout_ms=5000)
    page = MagicMock()
    page.get_by_role.return_value.first.is_visible.return_value = False
    assert not provider._click_show_more_posts(page=page, username="shop")
    page.get_by_role.return_value.first.click.assert_not_called()


def test_load_more_can_be_clicked_repeatedly_until_requested_limit() -> None:
    provider = PlaywrightInstagramProvider(timeout_ms=5000)
    batches = [
        [f"/p/POST{i:03d}/" for i in range(n)]
        for n in (12, 24, 36, 48)
    ]
    page, _ = profile_page(batches)
    current_batch = [0]
    anchors = page.locator.return_value
    page.locator.side_effect = lambda _: anchors
    anchors.count.side_effect = lambda: len(batches[current_batch[0]])
    anchors.nth.side_effect = lambda n: MagicMock(
        get_attribute=MagicMock(return_value=batches[current_batch[0]][n])
    )
    provider._scroll_profile_media_grid = lambda **kw: None

    button = page.get_by_role.return_value.first
    button.is_visible.side_effect = lambda: current_batch[0] < len(batches)-1
    button.click.side_effect = lambda **kw: current_batch.__setitem__(
        0, current_batch[0] + 1
    )

    result = provider._discover_media_urls(page=page, username="shop", max_items=40)
    assert len(result) == 40
    assert result[-1].endswith("POST039/")
    assert button.click.call_count == 3


def test_load_more_click_timeout_does_not_count_as_loaded() -> None:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    provider = PlaywrightInstagramProvider(timeout_ms=5000)
    page = MagicMock()
    button = page.get_by_role.return_value.first
    button.is_visible.return_value = True
    button.click.side_effect = PlaywrightTimeoutError("stalled")
    assert not provider._click_show_more_posts(page=page, username="shop")
