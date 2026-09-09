from __future__ import annotations

from app.integrations.selora.client import (
    SeloraApiResponseError,
)
from app.routes.web import (
    _remote_error_message,
)


def _error(
    *,
    code: str,
    status_code: int,
) -> SeloraApiResponseError:
    return SeloraApiResponseError(
        status_code=status_code,
        code=code,
        message=code,
        request_id="req-1",
    )


def test_workspace_locked_is_retryable() -> None:
    message, reason, retry_allowed = (
        _remote_error_message(
            _error(
                code="workspace_locked",
                status_code=423,
            )
        )
    )

    assert "اپراتور دیگری" in message
    assert reason is not None
    assert retry_allowed is True


def test_workspace_finalized_is_permanent_read_only() -> None:
    message, reason, retry_allowed = (
        _remote_error_message(
            _error(
                code="workspace_finalized",
                status_code=423,
            )
        )
    )

    assert "نهایی" in message
    assert reason is not None
    assert retry_allowed is False


def test_revision_conflict_is_retryable() -> None:
    message, reason, retry_allowed = (
        _remote_error_message(
            _error(
                code="revision_conflict",
                status_code=409,
            )
        )
    )

    assert "نسخه" in message
    assert reason is not None
    assert retry_allowed is True
