from __future__ import annotations

import re
import socket
import ssl
from typing import Iterable

import requests

from app.integrations.selora.client import (
    SeloraApiNetworkError,
    SeloraApiResponseError,
)


_MAX_TECHNICAL_LENGTH = 900


def install_selora_diagnostics() -> None:
    """Make Selora exceptions expose the actual transport/HTTP failure reason."""
    if getattr(SeloraApiNetworkError, "_selora_diagnostics_installed", False):
        return

    def _network_error_str(error: SeloraApiNetworkError) -> str:
        cause = error.__cause__
        if cause is None:
            return RuntimeError.__str__(error)
        return describe_network_failure(cause, stage=error.stage)

    def _response_error_str(error: SeloraApiResponseError) -> str:
        message = RuntimeError.__str__(error).strip() or "پاسخ API سلورا نامعتبر بود."
        details = [f"HTTP {error.status_code}"]
        if error.code:
            details.append(f"code={error.code}")
        if error.stage:
            details.append(f"stage={error.stage}")
        return f"{message} ({', '.join(details)})"

    SeloraApiNetworkError.__str__ = _network_error_str  # type: ignore[method-assign]
    SeloraApiResponseError.__str__ = _response_error_str  # type: ignore[method-assign]
    setattr(SeloraApiNetworkError, "_selora_diagnostics_installed", True)


def describe_network_failure(error: BaseException, *, stage: str = "") -> str:
    """Return a Persian operator-facing reason while preserving technical detail."""
    chain = tuple(_exception_chain(error))
    technical = _technical_summary(chain)
    lowered = technical.lower()

    if any(isinstance(item, requests.exceptions.ConnectTimeout) for item in chain):
        reason = "مهلت برقراری اتصال به سرور سلورا تمام شد"
    elif any(isinstance(item, requests.exceptions.ReadTimeout) for item in chain):
        reason = "اتصال برقرار شد اما پاسخ سلورا در زمان مجاز دریافت نشد"
    elif any(isinstance(item, requests.exceptions.ProxyError) for item in chain):
        reason = "اتصال از طریق Proxy ناموفق بود"
    elif (
        any(isinstance(item, requests.exceptions.SSLError) for item in chain)
        or any(isinstance(item, ssl.SSLError) for item in chain)
        or "ssl" in lowered
        or "tls" in lowered
        or "certificate" in lowered
    ):
        reason = "خطای SSL/TLS هنگام برقراری ارتباط امن با سلورا رخ داد"
    elif (
        any(isinstance(item, socket.gaierror) for item in chain)
        or "nameresolutionerror" in lowered
        or "getaddrinfo failed" in lowered
        or "name or service not known" in lowered
        or "temporary failure in name resolution" in lowered
    ):
        reason = "DNS نتوانست دامنه API سلورا را resolve کند"
    elif (
        "connection refused" in lowered
        or "actively refused" in lowered
        or "winerror 10061" in lowered
    ):
        reason = "سرور مقصد اتصال را رد کرد"
    elif (
        "connection reset" in lowered
        or "forcibly closed" in lowered
        or "connection aborted" in lowered
    ):
        reason = "اتصال شبکه در میانه ارتباط قطع یا reset شد"
    elif any(isinstance(item, requests.exceptions.Timeout) for item in chain):
        reason = "ارتباط با API سلورا timeout شد"
    elif any(isinstance(item, requests.exceptions.ConnectionError) for item in chain):
        reason = "اتصال شبکه به API سلورا برقرار نشد"
    else:
        reason = "ارتباط با API سلورا برقرار نشد"

    stage_text = f" | مرحله: {stage}" if stage else ""
    return f"{reason}{stage_text} | جزئیات فنی: {technical}"


def _exception_chain(error: BaseException) -> Iterable[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = error

    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _technical_summary(chain: tuple[BaseException, ...]) -> str:
    parts: list[str] = []
    for item in chain:
        text = re.sub(r"\s+", " ", str(item)).strip()
        label = type(item).__name__
        candidate = f"{label}: {text}" if text else label
        if candidate not in parts:
            parts.append(candidate)

    summary = " -> ".join(parts) or "Unknown network error"
    if len(summary) > _MAX_TECHNICAL_LENGTH:
        summary = summary[: _MAX_TECHNICAL_LENGTH - 3] + "..."
    return summary
