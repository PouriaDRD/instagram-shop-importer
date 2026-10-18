"""Operator-consented Instagram login for the local desktop importer.

Run from repository root:
    .venv/Scripts/python.exe -m app.crawler.instagram.connect_session

No username/password is requested by or provided to the importer. The user
signs in directly on Instagram in a separate browser launched by Playwright.
Only the authenticated browser storage state is saved under ignored instance/.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.config import Config
from app.crawler.instagram.playwright_provider import (
    INSTAGRAM_BASE_URL,
    PlaywrightInstagramProvider,
)


def state_path() -> Path:
    """The operator's private, git-ignored Instagram session state."""
    return Path(Config.INSTAGRAM_AUTH_STATE_PATH).expanduser().resolve()


def has_session_cookie(cookies: list[dict[str, object]]) -> bool:
    """Check cookie *names* only; never disclose actual session values."""
    return any(
        item.get("name") == "sessionid"
        and item.get("value")
        and str(item.get("domain", "")).lstrip(".").lower() == "instagram.com"
        for item in cookies
    )


def save_authenticated_state(context: object, destination: Path) -> None:
    """Save an authenticated session atomically, never replacing on failure."""
    # The typed Playwright context is duck-typed for easy offline testing.
    cookies = context.cookies(INSTAGRAM_BASE_URL)  # type: ignore[attr-defined]
    if not has_session_cookie(cookies):
        raise RuntimeError(
            "Instagram is not signed in in this browser. "
            "Complete login in the opened browser and try again."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".new")
    try:
        context.storage_state(path=str(temporary))  # type: ignore[attr-defined]
        # Validate JSON on disk, so a failed browser write cannot overwrite
        # an earlier working session.
        saved = json.loads(temporary.read_text(encoding="utf-8"))
        if not isinstance(saved, dict) or not has_session_cookie(saved.get("cookies", [])):
            raise RuntimeError("Browser did not save a valid Instagram session.")
        if os.name != "nt":
            temporary.chmod(0o600)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def connect() -> int:
    """Open a dedicated, temporary browser for manual operator login."""
    destination = state_path()
    print("[INFO] Opening Instagram in a new browser window.")
    print("[INFO] Sign in directly on Instagram (not in the Importer).")
    print("[INFO] After login finishes, return here and press Enter.")
    print("[INFO] Session cookies stay on this Windows computer under instance/.")
    print("[INFO] Protect this folder and never share its contents or commit it.")

    with sync_playwright() as playwright:
        browser_path = PlaywrightInstagramProvider._resolve_browser_executable()
        options: dict[str, object] = {"headless": False}
        if browser_path is not None:
            options["executable_path"] = str(browser_path)
        browser = playwright.chromium.launch(**options)
        try:
            context = browser.new_context(locale="en-US")
            try:
                page = context.new_page()
                page.goto(
                    f"{INSTAGRAM_BASE_URL}/accounts/login/",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                input("Press Enter when you have completed login: ")
                save_authenticated_state(context, destination)
            finally:
                context.close()
        finally:
            browser.close()

    print(f"[PASS] Instagram session connected: {destination}")
    print("[NEXT] Restart Selora Importer, then retry 20 posts.")
    return 0


def main() -> int:
    try:
        return connect()
    except (EOFError, KeyboardInterrupt):
        print("[STOP] Cancelled: existing Instagram session was preserved.")
        return 1
    except Exception as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
