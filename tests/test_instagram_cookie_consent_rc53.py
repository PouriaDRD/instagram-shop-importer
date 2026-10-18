"""RC5.3: operator-authorized Instagram cookie consent, without live requests."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.common.exceptions import InstagramAuthenticationRequiredError
from app.crawler.instagram.playwright_provider import PlaywrightInstagramProvider


@pytest.mark.parametrize("url", [
    "https://www.instagram.com/consent/?flow=user_cookie_choice_v2",
    "https://instagram.com/consent/",
])
def test_only_official_instagram_consent_is_recognized(url: str) -> None:
    assert PlaywrightInstagramProvider._is_instagram_cookie_consent_url(url)


@pytest.mark.parametrize("url", [
    "http://www.instagram.com/consent/",
    "https://evil.instagram.com/consent/",
    "https://www.instagram.com.evil.test/consent/",
    "https://www.instagram.com/anything/consent/",
    "https://www.instagram.com/accounts/login/",
])
def test_other_domains_and_pages_never_trigger_cookie_acceptance(url: str) -> None:
    page = MagicMock(url=url)
    assert PlaywrightInstagramProvider._accept_instagram_cookie_consent(page=page) is False
    page.get_by_role.assert_not_called()


@pytest.mark.parametrize("label", [
    "Allow all cookies", "Accept all cookies", "Allow essential and optional cookies",
    "Allow all", "پذیرش همه کوکی‌ها", "Alle Cookies akzeptieren"
])
def test_accept_all_cookie_label_is_supported(label: str) -> None:
    from app.crawler.instagram.playwright_provider import _COOKIE_ACCEPT_LABEL
    assert _COOKIE_ACCEPT_LABEL.fullmatch(label)


@pytest.mark.parametrize("label", [
    "Decline optional cookies", "Only allow essential cookies", "Reject all",
    "Continue", "Save preferences", "Not now",
])
def test_consent_never_selects_reject_or_generic_continue(label: str) -> None:
    from app.crawler.instagram.playwright_provider import _COOKIE_ACCEPT_LABEL
    assert not _COOKIE_ACCEPT_LABEL.fullmatch(label)


def test_cookie_consent_is_clicked_on_instagram_page() -> None:
    page = MagicMock(url="https://www.instagram.com/consent/?flow=user_cookie_choice_v2")
    page.get_by_role.return_value.first.is_visible.return_value = True
    assert PlaywrightInstagramProvider._accept_instagram_cookie_consent(page=page)
    page.get_by_role.return_value.first.click.assert_called_once()
    assert page.get_by_role.call_args.kwargs["name"].fullmatch("Allow all cookies")


def test_unrecognized_consent_is_explicit_failure_not_zero_posts() -> None:
    page = MagicMock(url="https://www.instagram.com/consent/?flow=user_cookie_choice_v2")
    page.get_by_role.return_value.first.is_visible.return_value = False
    with pytest.raises(InstagramAuthenticationRequiredError, match="cookie-consent"):
        PlaywrightInstagramProvider._accept_instagram_cookie_consent(page=page)


def test_profile_navigation_retries_after_consent_then_loads_target() -> None:
    page = MagicMock()
    page.goto.side_effect = lambda url, **kwargs: next_response(url)
    calls = [0]
    def next_response(url: str) -> SimpleNamespace:
        calls[0] += 1
        page.url = (
            "https://www.instagram.com/consent/?flow=user_cookie_choice_v2"
            if calls[0] == 1 else url
        )
        return SimpleNamespace(status=200)
    provider = PlaywrightInstagramProvider()
    def accept(*, page: MagicMock) -> bool:
        page.url = "https://www.instagram.com/"
        return True
    provider._accept_instagram_cookie_consent = accept
    target = "https://www.instagram.com/testshop/"
    result = provider._goto_instagram_page(page=page, url=target)
    assert result.status == 200
    assert calls[0] == 2
    assert page.url == target


def test_consented_page_redirect_loop_fails_explicitly() -> None:
    page = MagicMock(url="https://www.instagram.com/consent/?flow=user_cookie_choice_v2")
    page.goto.return_value.status = 200
    provider = PlaywrightInstagramProvider()
    provider._accept_instagram_cookie_consent = lambda *, page: True
    with pytest.raises(InstagramAuthenticationRequiredError, match="redirected back"):
        provider._goto_instagram_page(page=page, url="https://www.instagram.com/testshop/")
    assert page.goto.call_count == 3


def test_all_profile_and_media_navigations_use_consent_aware_wrapper() -> None:
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] /
            "app/crawler/instagram/playwright_provider.py").read_text(encoding="utf-8")
    assert text.count("self._goto_instagram_page(page=page") == 3
