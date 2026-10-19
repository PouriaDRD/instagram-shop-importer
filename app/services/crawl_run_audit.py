"""Private, durable, per-attempt crawl audit records.

No cookies, Instagram CDN URLs, access tokens, or raw media metadata are stored.
A source may be crawled repeatedly: each attempt gets a separate immutable id.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Any
from uuid import uuid4


_FIELDS = frozenset({
    "discovered_candidates", "detail_attempted", "detail_failed",
    "detail_succeeded", "unique_valid", "selected_posts", "synced_posts",
    "created_posts", "updated_posts", "download_total", "download_saved",
    "download_reused", "download_failed", "download_error", "bytes_downloaded",
})
_TERMINAL = frozenset({"completed", "cancelled", "failed"})


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class CrawlRunAudit:
    """Atomic JSON writes; independent of Flask/SQLAlchemy transaction scope."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()
        self._lock = RLock()
        self._active: dict[str, tuple[str, float]] = {}

    @staticmethod
    def _source(source_id: str) -> str:
        # Source ids normally are UUIDs. Never permit path separators/traversal.
        if not source_id or not all(c.isalnum() or c in "-_" for c in source_id):
            raise ValueError("Invalid crawl source id")
        return source_id[:80]

    def _path(self, source_id: str, run_id: str) -> Path:
        return self._root / self._source(source_id) / f"{run_id}.json"

    def _write(self, source_id: str, report: dict[str, Any]) -> None:
        path = self._path(source_id, report["run_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.stem}.{uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as fh:
                json.dump(report, fh, ensure_ascii=False, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def begin(self, source_id: str, *, requested: int | None,
              sort_order: str, signed_in: bool) -> str:
        run_id = uuid4().hex
        report: dict[str, Any] = {
            "run_id": run_id, "source_id": self._source(source_id),
            "status": "running", "started_at": _utc(), "finished_at": None,
            "duration_seconds": None, "requested_posts": requested,
            "sort_order": sort_order, "signed_in": bool(signed_in),
            "phase": "pending", "error_category": None, "warning": None,
            "discovered_candidates": 0, "detail_attempted": 0,
            "detail_failed": 0, "detail_succeeded": 0,
            "unique_valid": 0, "selected_posts": 0, "synced_posts": 0,
            "created_posts": 0, "updated_posts": 0,
            "download_total": 0, "download_saved": 0,
            "download_reused": 0, "download_failed": 0, "download_error": 0,
            "bytes_downloaded": 0,
        }
        with self._lock:
            if source_id in self._active:
                raise ValueError("Crawl audit already active for source")
            self._write(source_id, report)
            self._active[source_id] = (run_id, monotonic())
        return run_id

    def update(self, source_id: str, *, phase: str | None = None,
               metrics: dict[str, Any] | None = None,
               warning: str | None = None) -> None:
        with self._lock:
            active = self._active.get(source_id)
            if active is None:
                return
            report = self._read_path(self._path(source_id, active[0]))
            if report is None or report["status"] != "running":
                return
            if phase is not None:
                report["phase"] = str(phase)[:48]
            for key, value in (metrics or {}).items():
                if key in _FIELDS and type(value) is int and value >= 0:
                    report[key] = value
            if warning is not None:
                report["warning"] = str(warning)[:240]
            self._write(source_id, report)

    def finish(self, source_id: str, *, status: str,
               error_category: str | None = None) -> None:
        if status not in _TERMINAL:
            status = "failed"
        with self._lock:
            active = self._active.pop(source_id, None)
            if active is None:
                return
            report = self._read_path(self._path(source_id, active[0]))
            if report is None:
                return
            report["status"] = status
            report["phase"] = status
            report["finished_at"] = _utc()
            report["duration_seconds"] = round(monotonic() - active[1], 1)
            report["error_category"] = error_category[:80] if error_category else None
            if status == "completed":
                if report["download_error"]:
                    report["warning"] = "مرحله ذخیره رسانه‌ها با خطای کلی روبه‌رو شد؛ اطلاعات پست‌ها حفظ شده‌اند."
                elif report["download_failed"]:
                    report["warning"] = "تعدادی از فایل‌های رسانه‌ای دانلود نشده‌اند؛ امکان تلاش مجدد وجود دارد."
                elif report["detail_failed"]:
                    report["warning"] = "جزئیات تعدادی از کاندیدها در دسترس نبود؛ فقط پست‌های معتبر ثبت شدند."
            self._write(source_id, report)

    @staticmethod
    def _read_path(path: Path) -> dict[str, Any] | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, ValueError):
            return None

    def history(self, source_id: str, limit: int = 5) -> list[dict[str, Any]]:
        folder = self._root / self._source(source_id)
        if not folder.is_dir():
            return []
        reports: list[dict[str, Any]] = []
        for path in folder.glob("*.json"):
            record = self._read_path(path)
            if record is not None and record.get("source_id") == source_id:
                # A fresh process has no active worker from an earlier run.
                # Do not mislead operators with a permanently running report.
                active = self._active.get(source_id)
                if record.get("status") == "running" and (
                    active is None or active[0] != record.get("run_id")
                ):
                    record["status"] = "interrupted"
                    record["warning"] = "برنامه هنگام این اجرا بسته شده است؛ برای بازیابی، تلاش مجدد را انتخاب کنید."
                reports.append(record)
        reports.sort(key=lambda r: (r.get("started_at") or "", r.get("run_id") or ""), reverse=True)
        return reports[:max(0, min(limit, 50))]

    def latest(self, source_id: str) -> dict[str, Any] | None:
        entries = self.history(source_id, limit=1)
        return entries[0] if entries else None
