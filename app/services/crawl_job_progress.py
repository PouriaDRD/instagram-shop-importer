"""Thread-safe transient progress and cooperative cancellation for local crawls.

The database remains the canonical persisted crawl status. No credentials,
cookies, CDN URLs, or media bytes are stored in this registry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Event, RLock
from typing import Any


class CrawlCancelled(Exception):
    """Operator requested that the current crawl stop at a safe boundary."""


@dataclass(slots=True)
class _Job:
    cancelled: Event = field(default_factory=Event)
    phase: str = "pending"
    current: int = 0
    total: int | None = None
    saved: int = 0
    reused: int = 0
    failed: int = 0
    bytes_saved: int = 0
    finished: bool = False
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CrawlJobProgress:
    """Per-application registry. Cancellation never kills a thread forcibly."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._jobs: dict[str, _Job] = {}

    def begin(self, session_id: str) -> None:
        with self._lock:
            if session_id in self._jobs and not self._jobs[session_id].finished:
                raise ValueError("Crawl is already running for this source.")
            # Bound finished history; durable results are in SQL instead.
            if len(self._jobs) > 100:
                self._jobs = {key: job for key, job in self._jobs.items() if not job.finished}
            self._jobs[session_id] = _Job()

    def exists(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._jobs

    def request_cancel(self, session_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(session_id)
            if job is None or job.finished or job.cancelled.is_set():
                return False
            job.cancelled.set()
            job.phase = "stopping"
            job.updated_at = datetime.now(timezone.utc).isoformat()
            return True

    def check(self, session_id: str) -> None:
        with self._lock:
            job = self._jobs.get(session_id)
        if job is not None and job.cancelled.is_set():
            raise CrawlCancelled("Crawl stopped by operator.")

    def report(self, session_id: str, phase: str, current: int = 0,
               total: int | None = None, *, saved: int | None = None,
               reused: int | None = None, failed: int | None = None,
               bytes_saved: int | None = None) -> None:
        with self._lock:
            job = self._jobs.get(session_id)
            if job is None or job.finished or job.cancelled.is_set():
                return
            job.phase = phase
            job.current = current
            job.total = total
            for key, val in (("saved", saved), ("reused", reused),
                             ("failed", failed), ("bytes_saved", bytes_saved)):
                if val is not None:
                    setattr(job, key, val)
            job.updated_at = datetime.now(timezone.utc).isoformat()

    def finish(self, session_id: str, phase: str) -> None:
        with self._lock:
            job = self._jobs.get(session_id)
            if job:
                job.finished = True
                job.phase = phase
                job.updated_at = datetime.now(timezone.utc).isoformat()

    def snapshot(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(session_id)
            if job is None:
                return None
            return {
                "phase": job.phase,
                "current": job.current,
                "total": job.total,
                "saved": job.saved,
                "reused": job.reused,
                "failed": job.failed,
                "bytes_saved": job.bytes_saved,
                "cancel_requested": job.cancelled.is_set(),
                "finished": job.finished,
                "updated_at": job.updated_at,
            }
