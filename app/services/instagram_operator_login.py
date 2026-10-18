"""Bounded background browser sign-in, controlled by the desktop UI.

No Instagram credentials are requested, inspected or transmitted by Selora.
"""
from __future__ import annotations

import logging
import secrets
import threading
import time
from typing import Any

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from app.crawler.instagram.connect_session import has_session_cookie
from app.crawler.instagram.playwright_provider import (
    INSTAGRAM_BASE_URL,
    PlaywrightInstagramProvider,
)
from app.services.instagram_operator_accounts import InstagramOperatorAccounts

logger = logging.getLogger("app")
_LOGIN_TIMEOUT_SECONDS = 600


class LoginAlreadyRunning(RuntimeError):
    """Only one interactive Instagram sign-in window can run at once."""


class InstagramOperatorLogin:
    """Own a single local interactive login job without blocking Flask requests."""

    def __init__(self, accounts: InstagramOperatorAccounts) -> None:
        self.accounts = accounts
        self._lock = threading.RLock()
        self._job: dict[str, Any] | None = None
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None

    def start(self, label: str) -> dict[str, Any]:
        label = " ".join(label.strip().split())
        if not 2 <= len(label) <= 50 or any(ord(ch) < 32 for ch in label):
            raise ValueError("نام حساب باید بین ۲ تا ۵۰ کاراکتر باشد.")
        with self._lock:
            if self._job is not None and self._job["state"] in {"opening", "waiting"}:
                raise LoginAlreadyRunning("یک پنجره ورود از قبل باز است.")
            self._cancel = threading.Event()
            job_id = secrets.token_hex(16)
            self._job = {"id": job_id, "state": "opening",
                         "message": "در حال باز کردن پنجره اینستاگرام...",
                         "account_id": None}
            thread = threading.Thread(
                target=self._run,
                args=(job_id, label, self._cancel),
                name="instagram-operator-sign-in",
                daemon=True,
            )
            self._worker = thread
            thread.start()
            return self.status(job_id)

    def status(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            if self._job is None or self._job["id"] != job_id:
                raise LookupError("فرآیند ورود پیدا نشد.")
            return dict(self._job)

    def cancel(self, job_id: str) -> None:
        with self._lock:
            if self._job is None or self._job["id"] != job_id:
                raise LookupError("فرآیند ورود پیدا نشد.")
            if self._job["state"] in {"opening", "waiting"}:
                self._cancel.set()

    def shutdown(self) -> None:
        """Cancel an open login before the desktop runtime safely exits."""
        with self._lock:
            self._cancel.set()
            worker = self._worker
        if worker is not None and worker is not threading.current_thread() and worker.is_alive():
            worker.join(timeout=4)

    def _update(self, job_id: str, **values: Any) -> None:
        with self._lock:
            if self._job is not None and self._job["id"] == job_id:
                if self._job["state"] in {"connected", "cancelled"} and values.get("state") == "failed":
                    return
                self._job.update(values)

    def _run(self, job_id: str, label: str, cancel: threading.Event) -> None:
        try:
            with sync_playwright() as playwright:
                browser_path = PlaywrightInstagramProvider._resolve_browser_executable()
                options: dict[str, Any] = {"headless": False}
                if browser_path is not None:
                    options["executable_path"] = str(browser_path)
                browser = playwright.chromium.launch(**options)
                try:
                    context = browser.new_context(locale="en-US")
                    try:
                        page = context.new_page()
                        page.goto(f"{INSTAGRAM_BASE_URL}/accounts/login/",
                                  wait_until="domcontentloaded", timeout=60000)
                        self._update(job_id, state="waiting",
                                     message="در پنجره اینستاگرام وارد حساب شوید؛ کد دو‌مرحله‌ای را همان‌جا ثبت کنید.")
                        deadline = time.monotonic() + _LOGIN_TIMEOUT_SECONDS
                        consecutive = 0
                        while time.monotonic() < deadline:
                            if cancel.is_set():
                                self._update(job_id, state="cancelled",
                                             message="ورود لغو شد؛ هیچ حسابی ذخیره نشد.")
                                return
                            if not browser.is_connected() or page.is_closed():
                                raise RuntimeError("پنجره اینستاگرام بسته شد. دوباره تلاش کنید.")
                            page.wait_for_timeout(1000)
                            # A valid login can redirect to Instagram's
                            # cookie-choice screen. Accept the cookies before
                            # saving the operator's browser storage state.
                            if PlaywrightInstagramProvider._is_instagram_cookie_consent_url(page.url):
                                self._update(job_id, state="waiting",
                                             message="در حال پذیرش خودکار کوکی‌های اینستاگرام...")
                                PlaywrightInstagramProvider._accept_instagram_cookie_consent(page=page)
                                page.wait_for_timeout(700)
                            cookies = context.cookies(INSTAGRAM_BASE_URL)
                            current_url = page.url.lower()
                            blocked = any(part in current_url for part in (
                                "/accounts/login", "/challenge", "/checkpoint", "/two_factor", "/consent"
                            ))
                            if has_session_cookie(cookies) and not blocked:
                                consecutive += 1
                            else:
                                consecutive = 0
                            if consecutive >= 2:
                                if cancel.is_set():
                                    self._update(job_id, state="cancelled",
                                                 message="ورود لغو شد؛ هیچ حسابی ذخیره نشد.")
                                    return
                                account = self.accounts.connect_from_browser(
                                    label=label, context=context
                                )
                                self._update(
                                    job_id, state="connected", account_id=account["id"],
                                    message="نشست حساب ذخیره شد. می‌توانید در فرم کراول انتخابش کنید.",
                                )
                                return
                        raise RuntimeError("مهلت ۱۰ دقیقه‌ای ورود به پایان رسید. دوباره تلاش کنید.")
                    finally:
                        context.close()
                finally:
                    browser.close()
        except (PlaywrightError, RuntimeError, OSError, ValueError) as exc:
            # Do not leak cookie values, browser storage, or page contents.
            logger.warning("Instagram operator browser login did not complete: %s", type(exc).__name__)
            if cancel.is_set():
                self._update(job_id, state="cancelled", message="ورود لغو شد؛ هیچ حسابی ذخیره نشد.")
            else:
                self._update(job_id, state="failed",
                             message="ورود کامل نشد. پنجره را بررسی و دوباره تلاش کنید.")
        except Exception:
            logger.exception("Unexpected Instagram operator sign-in failure")
            self._update(job_id, state="failed",
                         message="اجرای مرورگر با مشکل روبه‌رو شد. لاگ برنامه را بررسی کنید.")
