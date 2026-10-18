"""Account-session pagination regression; never use real login credentials."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.config import Config
from app.crawler.instagram.connect_session import (
    has_session_cookie,
    save_authenticated_state,
)
from app.crawler.instagram.playwright_provider import PlaywrightInstagramProvider


def test_session_cookie_validation() -> None:
    assert has_session_cookie([{
        "name": "sessionid", "value": "x", "domain": ".instagram.com"
    }])
    assert not has_session_cookie([{
        "name": "csrftoken", "value": "x", "domain": ".instagram.com"
    }])
    assert not has_session_cookie([{
        "name": "sessionid", "value": "", "domain": ".instagram.com"
    }])
    assert not has_session_cookie([{
        "name": "sessionid", "value": "x", "domain": ".evil.invalid"
    }])


def test_atomic_auth_state_preserves_old_on_failed_login(tmp_path: Path) -> None:
    destination = tmp_path / "session.json"
    destination.write_text('OLD', encoding='utf-8')
    context = MagicMock()
    context.cookies.return_value = []
    with pytest.raises(RuntimeError, match="not signed in"):
        save_authenticated_state(context, destination)
    assert destination.read_text(encoding='utf-8') == 'OLD'
    context.storage_state.assert_not_called()


def test_valid_login_saves_session_state(tmp_path: Path) -> None:
    destination = tmp_path / 'private' / 'session.json'
    cookie = {"name": "sessionid", "value": "sensitive", "domain": ".instagram.com"}
    context = MagicMock()
    context.cookies.return_value = [cookie]
    def save(*, path: str) -> None:
        Path(path).write_text(json.dumps({"cookies": [cookie], "origins": []}), encoding='utf-8')
    context.storage_state.side_effect = save
    save_authenticated_state(context, destination)
    assert json.loads(destination.read_text(encoding='utf-8'))['cookies'][0]['name'] == 'sessionid'
    assert not (destination.parent / (destination.name + '.new')).exists()


def test_invalid_saved_state_does_not_replace_good_one(tmp_path: Path) -> None:
    destination = tmp_path / 'session.json'
    destination.write_text('OLD', encoding='utf-8')
    context = MagicMock()
    context.cookies.return_value = [{"name":"sessionid","value":"v","domain":".instagram.com"}]
    context.storage_state.side_effect = lambda *, path: Path(path).write_text('{}', encoding='utf-8')
    with pytest.raises(RuntimeError, match="valid Instagram session"):
        save_authenticated_state(context, destination)
    assert destination.read_text(encoding='utf-8') == 'OLD'


@pytest.mark.parametrize('saved', [False, True])
def test_importer_reuses_operator_login_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, saved: bool
) -> None:
    auth_path = tmp_path / 'instance' / 'instagram_auth' / 'storage_state.json'
    if saved:
        auth_path.parent.mkdir(parents=True)
        auth_path.write_text('{"cookies":[],"origins":[]}', encoding='utf-8')
    monkeypatch.setattr(Config, 'INSTAGRAM_AUTH_STATE_PATH', str(auth_path))
    provider = PlaywrightInstagramProvider(timeout_ms=5000)
    p = MagicMock()
    b = MagicMock()
    c = MagicMock()
    p.chromium.launch.return_value = b
    b.new_context.return_value = c
    with patch('app.crawler.instagram.playwright_provider.sync_playwright') as mocked, patch.object(
        provider, '_resolve_browser_executable', return_value=None
    ):
        mocked.return_value.start.return_value = p
        with provider._browser_context() as opened:
            assert opened is c
    options = b.new_context.call_args.kwargs
    assert ('storage_state' in options) == saved
    if saved:
        assert options['storage_state'] == str(auth_path)


def test_show_more_button_scrolls_before_click() -> None:
    provider = PlaywrightInstagramProvider(timeout_ms=5000)
    page = MagicMock()
    button = page.get_by_role.return_value.first
    button.is_visible.return_value = True
    assert provider._click_show_more_posts(page=page, username='shop')
    button.scroll_into_view_if_needed.assert_called_once_with(timeout=4000)
    button.click.assert_called_once_with(timeout=5000)
