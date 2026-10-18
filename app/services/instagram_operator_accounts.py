"""Local, multi-account Instagram sessions for operators.

The registry never contains credentials. Browser storage states live beneath
Flask's ignored instance directory and are never returned from web handlers.
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.crawler.instagram.connect_session import (
    has_session_cookie,
    save_authenticated_state,
)

_ACCOUNT_ID = re.compile(r"^[0-9a-f]{32}$")
_REGISTRY_LOCK = threading.RLock()


class AccountSelectionError(ValueError):
    """Requested Instagram account does not have a usable local session."""


class InstagramOperatorAccounts:
    """Persist separately named account sessions on the current workstation."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.registry = self.root / "accounts.json"

    def _load(self) -> list[dict[str, str]]:
        if not self.registry.is_file():
            return []
        result = json.loads(self.registry.read_text(encoding="utf-8"))
        if not isinstance(result, list):
            raise RuntimeError("Instagram operator account registry is invalid.")
        return [item for item in result if isinstance(item, dict)]

    def _save(self, items: list[dict[str, str]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / f"accounts.{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_text(
                json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            if os.name != "nt":
                temporary.chmod(0o600)
            os.replace(temporary, self.registry)
        finally:
            temporary.unlink(missing_ok=True)

    def _state_path(self, account_id: str) -> Path:
        if not _ACCOUNT_ID.fullmatch(account_id):
            raise AccountSelectionError("شناسه حساب اینستاگرام معتبر نیست.")
        return self.root / account_id / "storage_state.json"

    @staticmethod
    def _usable_state(path: Path) -> bool:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cookies = data.get("cookies", [])
            now = datetime.now(timezone.utc).timestamp()
            return isinstance(cookies, list) and has_session_cookie([
                cookie for cookie in cookies if isinstance(cookie, dict)
                and (not isinstance(cookie.get("expires"), (float, int))
                     or float(cookie["expires"]) <= 0
                     or float(cookie["expires"]) > now)
            ])
        except (OSError, ValueError, TypeError, AttributeError):
            return False

    def list_accounts(self) -> list[dict[str, Any]]:
        with _REGISTRY_LOCK:
            return [{
                "id": item["id"],
                "label": item["label"],
                "connected_at": item["connected_at"],
                "saved_session": self._usable_state(self._state_path(item["id"])),
            } for item in self._load()
            if (isinstance(item.get("id"), str)
                and _ACCOUNT_ID.fullmatch(item["id"])
                and isinstance(item.get("label"), str)
                and isinstance(item.get("connected_at"), str))]

    def get_state_path(self, account_id: str) -> Path:
        with _REGISTRY_LOCK:
            if not any(item["id"] == account_id for item in self.list_accounts()):
                raise AccountSelectionError("حساب اینستاگرام انتخاب‌شده وجود ندارد.")
            path = self._state_path(account_id)
            if not self._usable_state(path):
                raise AccountSelectionError("نشست اینستاگرام این حساب موجود نیست یا منقضی شده است.")
            return path

    def connect_from_browser(self, *, label: str, context: Any) -> dict[str, str]:
        label = " ".join(label.strip().split())
        if not 2 <= len(label) <= 50 or any(ord(ch) < 32 for ch in label):
            raise ValueError("نام حساب باید بین ۲ تا ۵۰ کاراکتر باشد.")
        account_id = uuid.uuid4().hex
        state = self._state_path(account_id)
        with _REGISTRY_LOCK:
            try:
                save_authenticated_state(context, state)
                item = {
                    "id": account_id,
                    "label": label,
                    "connected_at": datetime.now(timezone.utc).isoformat(),
                }
                items = self._load()
                items.append(item)
                self._save(items)
                return item
            except Exception:
                state.unlink(missing_ok=True)
                try:
                    state.parent.rmdir()
                except OSError:
                    pass
                raise

    def remove(self, account_id: str) -> bool:
        with _REGISTRY_LOCK:
            items = self._load()
            kept = [item for item in items if item.get("id") != account_id]
            if len(kept) == len(items):
                return False
            state = self._state_path(account_id)
            # Delete the registry entry first; this prevents new jobs from
            # selecting the account even if the subsequent unlink fails.
            self._save(kept)
            state.unlink(missing_ok=True)
            try:
                state.parent.rmdir()
            except OSError:
                pass
            return True
