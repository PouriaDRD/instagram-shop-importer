"""Operator Instagram account security and UI regression tests.

All examples use fake cookies. No real passwords or Instagram requests.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app.crawler.instagram.connect_session import has_session_cookie
from app.crawler.instagram.playwright_provider import PlaywrightInstagramProvider
from app.services.background_crawl_runner import BackgroundCrawlRunner
from app.services.instagram_operator_accounts import (
    AccountSelectionError,
    InstagramOperatorAccounts,
)
from app.services.instagram_operator_login import (
    InstagramOperatorLogin,
    LoginAlreadyRunning,
)


def fake_context() -> MagicMock:
    context = MagicMock()
    cookie = {"name": "sessionid", "value": "REDACTED", "domain": ".instagram.com", "expires": -1}
    context.cookies.return_value = [cookie]
    def storage_state(*, path: str) -> None:
        Path(path).write_text(json.dumps({"cookies": [cookie], "origins": []}), encoding="utf-8")
    context.storage_state.side_effect = storage_state
    return context


def test_cookie_domain_must_match_real_instagram() -> None:
    assert has_session_cookie([{"name": "sessionid", "value": "x", "domain": ".instagram.com"}])
    assert not has_session_cookie([{"name": "sessionid", "value": "x", "domain": "badinstagram.com"}])
    assert not has_session_cookie([{"name": "sessionid", "value": "x", "domain": ".instagram.com.evil.org"}])


def test_add_two_sessions_keeps_isolated_private_files(tmp_path: Path) -> None:
    accounts = InstagramOperatorAccounts(tmp_path / "profiles")
    a = accounts.connect_from_browser(label=" اپراتور    یک ", context=fake_context())
    b = accounts.connect_from_browser(label="اپراتور دو", context=fake_context())
    assert a["id"] != b["id"]
    assert a["label"] == "اپراتور یک"
    assert len(accounts.list_accounts()) == 2
    a_file = accounts.get_state_path(a["id"])
    b_file = accounts.get_state_path(b["id"])
    assert a_file != b_file
    assert a_file.is_file() and b_file.is_file()
    registry = (tmp_path / "profiles" / "accounts.json").read_text(encoding="utf-8")
    assert "REDACTED" not in registry
    assert "sessionid" not in registry
    assert "REDACTED" in a_file.read_text(encoding="utf-8")
    assert not (tmp_path / "profiles" / "accounts.json.new").exists()


def test_account_removal_does_not_delete_other_operator(tmp_path: Path) -> None:
    accounts = InstagramOperatorAccounts(tmp_path / "accounts")
    first = accounts.connect_from_browser(label="Account A", context=fake_context())
    second = accounts.connect_from_browser(label="Account B", context=fake_context())
    old_state = accounts.get_state_path(first["id"])
    new_state = accounts.get_state_path(second["id"])
    assert accounts.remove(first["id"])
    assert not old_state.exists()
    assert new_state.is_file()
    assert [a["id"] for a in accounts.list_accounts()] == [second["id"]]
    with pytest.raises(AccountSelectionError):
        accounts.get_state_path(first["id"])


def test_reject_unknown_and_path_traversal(tmp_path: Path) -> None:
    accounts = InstagramOperatorAccounts(tmp_path / "accounts")
    for account_id in ("../../secret", "x", "a" * 32):
        with pytest.raises(AccountSelectionError):
            accounts.get_state_path(account_id)


def test_stale_cookie_is_not_selectable(tmp_path: Path) -> None:
    accounts = InstagramOperatorAccounts(tmp_path / "accounts")
    item = accounts.connect_from_browser(label="Expired test", context=fake_context())
    state = accounts.get_state_path(item["id"])
    data = json.loads(state.read_text(encoding="utf-8"))
    data["cookies"][0]["expires"] = 1
    state.write_text(json.dumps(data), encoding="utf-8")
    assert not accounts.list_accounts()[0]["saved_session"]
    with pytest.raises(AccountSelectionError):
        accounts.get_state_path(item["id"])


def test_invalid_login_never_persists_credentials(tmp_path: Path) -> None:
    accounts = InstagramOperatorAccounts(tmp_path / "accounts")
    context = MagicMock()
    context.cookies.return_value = []
    with pytest.raises(RuntimeError):
        accounts.connect_from_browser(label="Broken", context=context)
    assert accounts.list_accounts() == []
    assert not list((tmp_path / "accounts").glob("*/storage_state.json"))


def test_failed_registry_write_rolls_back_saved_cookie(tmp_path: Path) -> None:
    accounts = InstagramOperatorAccounts(tmp_path / "accounts")
    with patch.object(accounts, "_save", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            accounts.connect_from_browser(label="Operator", context=fake_context())
    assert not list((tmp_path / "accounts").glob("*/storage_state.json"))


def test_only_one_browser_login_is_opened(tmp_path: Path) -> None:
    manager = InstagramOperatorLogin(InstagramOperatorAccounts(tmp_path))
    with patch("app.services.instagram_operator_login.threading.Thread") as thread_class:
        job = manager.start("اپراتور تست")
        assert job["state"] == "opening"
        with pytest.raises(LoginAlreadyRunning):
            manager.start("اپراتور دیگر")
        manager.cancel(job["id"])
        assert manager._cancel.is_set()
        thread_class.return_value.start.assert_called_once()
    with pytest.raises(LookupError):
        manager.status("invalid")


def test_no_failed_cleanup_can_override_saved_success(tmp_path: Path) -> None:
    manager = InstagramOperatorLogin(InstagramOperatorAccounts(tmp_path))
    with patch("app.services.instagram_operator_login.threading.Thread"):
        job = manager.start("Operator")
    manager._update(job["id"], state="connected", account_id="x")
    manager._update(job["id"], state="failed", message="cleanup")
    assert manager.status(job["id"])["state"] == "connected"


def test_crawl_runner_pins_account_path_to_job(app: Flask) -> None:
    runner = BackgroundCrawlRunner()
    with patch("app.services.background_crawl_runner.threading.Thread") as thread_class:
        runner.start(app=app, session_id="a", max_items=20, auth_state_path="C:/operator1/state.json")
    assert thread_class.call_args.kwargs["kwargs"]["auth_state_path"] == "C:/operator1/state.json"


def test_crawl_worker_uses_pinned_account(app: Flask) -> None:
    with (
        patch("app.services.background_crawl_runner.CrawlSessionRepository"),
        patch("app.services.background_crawl_runner.CrawlService") as service,
        patch("app.services.background_crawl_runner.PlaywrightInstagramProvider") as provider,
        patch("app.services.background_crawl_runner.db.session.remove"),
    ):
        BackgroundCrawlRunner._run(app=app, session_id="a", max_items=20,
                                   auth_state_path="C:/operator2/state.json")
    provider.assert_called_once_with(auth_state_path="C:/operator2/state.json")
    service.return_value.run.assert_called_once_with(session_id="a", max_items=20)


def test_provider_explicit_session_never_falls_back_to_anonymous(tmp_path: Path) -> None:
    provider = PlaywrightInstagramProvider(auth_state_path=str(tmp_path / "missing.json"))
    playwright = MagicMock()
    playwright.chromium.launch.return_value = MagicMock()
    with (
        patch("app.crawler.instagram.playwright_provider.sync_playwright") as start,
        patch.object(provider, "_resolve_browser_executable", return_value=None),
    ):
        start.return_value.start.return_value = playwright
        with pytest.raises(Exception, match="selected operator Instagram session is missing"):
            with provider._browser_context():
                pass


def test_account_manager_page_renders(client: FlaskClient) -> None:
    response = client.get("/instagram/accounts")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "حساب‌های اینستاگرام" in html
    assert "X-Instagram-Accounts-Token" in html
    assert 'type="password"' not in html


def test_account_manager_rejects_cross_origin_and_missing_csrf(app: Flask, client: FlaskClient) -> None:
    assert client.post("/instagram/accounts/start", json={"label": "Operator"}).status_code == 403
    token = app.extensions["instagram_operator_csrf"]
    assert client.post(
        "/instagram/accounts/start", json={"label": "Operator"},
        headers={"X-Instagram-Accounts-Token": token, "Origin": "https://evil.example"}
    ).status_code == 403
    assert client.post(
        "/instagram/accounts/start", json={"label": "Operator"},
        headers={"X-Instagram-Accounts-Token": token, "Host": "evil.example"}
    ).status_code == 403


def test_account_login_starts_without_blocking_flask(app: Flask, client: FlaskClient) -> None:
    token = app.extensions["instagram_operator_csrf"]
    with patch.object(app.extensions["instagram_operator_login"], "start", return_value={
        "id": "j1", "state": "opening", "message": "opening", "account_id": None
    }) as starter:
        response = client.post("/instagram/accounts/start", json={"label": "Operator"},
                               headers={"X-Instagram-Accounts-Token": token})
    assert response.status_code == 202
    assert response.get_json()["state"] == "opening"
    starter.assert_called_once_with("Operator")


def test_invalid_instagram_account_cannot_start_crawl(client: FlaskClient) -> None:
    response = client.post("/crawl", data={
        "username": "shop", "max_items": "20", "instagram_account": "../../invalid"
    })
    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_instagram_account"


def test_browser_login_saves_one_valid_operator_state(tmp_path: Path) -> None:
    import threading
    accounts = InstagramOperatorAccounts(tmp_path / "accounts")
    manager = InstagramOperatorLogin(accounts)
    with patch("app.services.instagram_operator_login.threading.Thread"):
        job = manager.start("Operator One")

    fake_browser = MagicMock()
    fake_browser.is_connected.return_value = True
    browser_context = fake_context()
    fake_page = MagicMock()
    fake_page.is_closed.return_value = False
    fake_page.url = "https://www.instagram.com/"
    browser_context.new_page.return_value = fake_page
    fake_browser.new_context.return_value = browser_context
    fake_playwright = MagicMock()
    fake_playwright.chromium.launch.return_value = fake_browser

    with (
        patch("app.services.instagram_operator_login.sync_playwright") as play,
        patch("app.services.instagram_operator_login.PlaywrightInstagramProvider._resolve_browser_executable", return_value=None),
    ):
        play.return_value.__enter__.return_value = fake_playwright
        manager._run(job["id"], "Operator One", threading.Event())

    state = manager.status(job["id"])
    assert state["state"] == "connected"
    assert state["account_id"]
    assert accounts.get_state_path(state["account_id"]).is_file()
    browser_context.storage_state.assert_called_once()
    browser_context.close.assert_called_once()
    fake_browser.close.assert_called_once()


def test_browser_login_does_not_save_session_during_challenge(tmp_path: Path) -> None:
    import threading
    accounts = InstagramOperatorAccounts(tmp_path / "accounts")
    manager = InstagramOperatorLogin(accounts)
    with patch("app.services.instagram_operator_login.threading.Thread"):
        job = manager.start("Operator Two")

    cancellation = threading.Event()
    fake_browser = MagicMock()
    fake_browser.is_connected.return_value = True
    browser_context = fake_context()
    fake_page = MagicMock()
    fake_page.is_closed.return_value = False
    fake_page.url = "https://www.instagram.com/challenge/verification/"
    fake_page.wait_for_timeout.side_effect = lambda _: cancellation.set()
    browser_context.new_page.return_value = fake_page
    fake_browser.new_context.return_value = browser_context
    fake_playwright = MagicMock()
    fake_playwright.chromium.launch.return_value = fake_browser
    with (
        patch("app.services.instagram_operator_login.sync_playwright") as play,
        patch("app.services.instagram_operator_login.PlaywrightInstagramProvider._resolve_browser_executable", return_value=None),
    ):
        play.return_value.__enter__.return_value = fake_playwright
        manager._run(job["id"], "Operator Two", cancellation)
    assert manager.status(job["id"])["state"] == "cancelled"
    assert accounts.list_accounts() == []
    browser_context.storage_state.assert_not_called()


def test_sign_in_window_cancels_on_safe_shutdown(tmp_path: Path) -> None:
    accounts = InstagramOperatorAccounts(tmp_path / "accounts")
    manager = InstagramOperatorLogin(accounts)
    with patch("app.services.instagram_operator_login.threading.Thread") as thread_class:
        job = manager.start("Operator")
        thread_class.return_value.is_alive.return_value = True
        manager.shutdown()
    assert manager._cancel.is_set()
    thread_class.return_value.join.assert_called_once_with(timeout=4)
    assert manager.status(job["id"])["state"] == "opening"
