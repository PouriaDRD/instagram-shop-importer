from __future__ import annotations

from unittest.mock import MagicMock, patch

from flask import Flask

from app.models import CrawlSession
from app.services.background_crawl_runner import (
    BackgroundCrawlRunner,
)


def test_start_creates_daemon_thread(
    app: Flask,
) -> None:
    runner = BackgroundCrawlRunner()

    with patch("app.services.background_crawl_runner.threading.Thread") as thread_class:
        thread = MagicMock()
        thread_class.return_value = thread

        runner.start(
            app=app,
            session_id="session-123",
            max_items=25,
        )

        thread_class.assert_called_once()

        _, kwargs = thread_class.call_args

        assert kwargs["target"] == runner._run
        assert kwargs["name"] == "crawl-session-123"
        assert kwargs["daemon"] is True

        assert kwargs["kwargs"] == {
            "app": app,
            "session_id": "session-123",
            "max_items": 25,
        }

        thread.start.assert_called_once_with()


def test_background_run_executes_service(
    app: Flask,
) -> None:
    repository = MagicMock()
    provider = MagicMock()
    service = MagicMock()

    with (
        patch(
            "app.services.background_crawl_runner." "CrawlSessionRepository",
            return_value=repository,
        ),
        patch(
            "app.services.background_crawl_runner." "PlaywrightInstagramProvider",
            return_value=provider,
        ),
        patch(
            "app.services.background_crawl_runner." "CrawlService",
            return_value=service,
        ) as service_class,
        patch(
            "app.services.background_crawl_runner." "db.session.remove"
        ) as remove_session,
    ):
        BackgroundCrawlRunner._run(
            app=app,
            session_id="abc",
            max_items=40,
        )

    service_class.assert_called_once_with(
        provider=provider,
        repository=repository,
    )

    service.run.assert_called_once_with(
        session_id="abc",
        max_items=40,
    )

    remove_session.assert_called_once_with()


def test_background_run_supports_none_max_items(
    app: Flask,
) -> None:
    repository = MagicMock()
    provider = MagicMock()
    service = MagicMock()

    with (
        patch(
            "app.services.background_crawl_runner." "CrawlSessionRepository",
            return_value=repository,
        ),
        patch(
            "app.services.background_crawl_runner." "PlaywrightInstagramProvider",
            return_value=provider,
        ),
        patch(
            "app.services.background_crawl_runner." "CrawlService",
            return_value=service,
        ),
        patch("app.services.background_crawl_runner." "db.session.remove"),
    ):
        BackgroundCrawlRunner._run(
            app=app,
            session_id="abc",
            max_items=None,
        )

    service.run.assert_called_once_with(
        session_id="abc",
        max_items=None,
    )


def test_unexpected_service_failure_triggers_recovery(
    app: Flask,
) -> None:
    repository = MagicMock()
    service = MagicMock()

    failure = RuntimeError("unexpected failure")

    service.run.side_effect = failure

    with (
        patch(
            "app.services.background_crawl_runner." "CrawlSessionRepository",
            return_value=repository,
        ),
        patch("app.services.background_crawl_runner." "PlaywrightInstagramProvider"),
        patch(
            "app.services.background_crawl_runner." "CrawlService",
            return_value=service,
        ),
        patch.object(
            BackgroundCrawlRunner,
            "_recover_failed_session",
        ) as recover,
        patch("app.services.background_crawl_runner." "db.session.remove"),
    ):
        BackgroundCrawlRunner._run(
            app=app,
            session_id="broken-session",
            max_items=5,
        )

    recover.assert_called_once_with(
        repository=repository,
        session_id="broken-session",
        error=failure,
    )


def test_db_session_is_removed_after_success(
    app: Flask,
) -> None:
    service = MagicMock()

    with (
        patch("app.services.background_crawl_runner." "CrawlSessionRepository"),
        patch("app.services.background_crawl_runner." "PlaywrightInstagramProvider"),
        patch(
            "app.services.background_crawl_runner." "CrawlService",
            return_value=service,
        ),
        patch(
            "app.services.background_crawl_runner." "db.session.remove"
        ) as remove_session,
    ):
        BackgroundCrawlRunner._run(
            app=app,
            session_id="success",
            max_items=1,
        )

    remove_session.assert_called_once_with()


def test_db_session_is_removed_after_failure(
    app: Flask,
) -> None:
    service = MagicMock()
    service.run.side_effect = RuntimeError("failure")

    with (
        patch("app.services.background_crawl_runner." "CrawlSessionRepository"),
        patch("app.services.background_crawl_runner." "PlaywrightInstagramProvider"),
        patch(
            "app.services.background_crawl_runner." "CrawlService",
            return_value=service,
        ),
        patch.object(
            BackgroundCrawlRunner,
            "_recover_failed_session",
        ),
        patch(
            "app.services.background_crawl_runner." "db.session.remove"
        ) as remove_session,
    ):
        BackgroundCrawlRunner._run(
            app=app,
            session_id="failure",
            max_items=1,
        )

    remove_session.assert_called_once_with()


def test_remove_failure_does_not_escape(
    app: Flask,
) -> None:
    service = MagicMock()

    with (
        patch("app.services.background_crawl_runner." "CrawlSessionRepository"),
        patch("app.services.background_crawl_runner." "PlaywrightInstagramProvider"),
        patch(
            "app.services.background_crawl_runner." "CrawlService",
            return_value=service,
        ),
        patch(
            "app.services.background_crawl_runner." "db.session.remove",
            side_effect=RuntimeError("remove exploded"),
        ),
    ):
        BackgroundCrawlRunner._run(
            app=app,
            session_id="abc",
            max_items=1,
        )


def test_recovery_rolls_back_before_reload(
    app: Flask,
) -> None:
    repository = MagicMock()

    session = MagicMock(
        spec=CrawlSession,
    )
    session.id = "session-1"

    repository.get.return_value = session

    with (
        app.app_context(),
        patch(
            "app.services.background_crawl_runner." "db.session.rollback"
        ) as rollback,
    ):
        BackgroundCrawlRunner._recover_failed_session(
            repository=repository,
            session_id="session-1",
            error=RuntimeError("boom"),
        )

    rollback.assert_called_once_with()

    repository.get.assert_called_once_with(
        session_id="session-1",
    )

    repository.mark_failed.assert_called_once_with(
        session=session,
        error_message="boom",
    )


def test_recovery_handles_missing_session(
    app: Flask,
) -> None:
    repository = MagicMock()
    repository.get.return_value = None

    with (
        app.app_context(),
        patch("app.services.background_crawl_runner." "db.session.rollback"),
    ):
        BackgroundCrawlRunner._recover_failed_session(
            repository=repository,
            session_id="missing",
            error=RuntimeError("boom"),
        )

    repository.mark_failed.assert_not_called()


def test_recovery_handles_repository_get_failure(
    app: Flask,
) -> None:
    repository = MagicMock()

    repository.get.side_effect = RuntimeError("database unavailable")

    with (
        app.app_context(),
        patch("app.services.background_crawl_runner." "db.session.rollback"),
    ):
        BackgroundCrawlRunner._recover_failed_session(
            repository=repository,
            session_id="abc",
            error=RuntimeError("crawl failed"),
        )

    repository.mark_failed.assert_not_called()


def test_recovery_handles_rollback_failure(
    app: Flask,
) -> None:
    repository = MagicMock()

    session = MagicMock(
        spec=CrawlSession,
    )

    repository.get.return_value = session

    with (
        app.app_context(),
        patch(
            "app.services.background_crawl_runner." "db.session.rollback",
            side_effect=RuntimeError("rollback failed"),
        ),
    ):
        BackgroundCrawlRunner._recover_failed_session(
            repository=repository,
            session_id="abc",
            error=RuntimeError("crawl failed"),
        )

    repository.get.assert_called_once_with(
        session_id="abc",
    )

    repository.mark_failed.assert_called_once()


def test_recovery_handles_mark_failed_failure(
    app: Flask,
) -> None:
    repository = MagicMock()

    session = MagicMock(
        spec=CrawlSession,
    )

    repository.get.return_value = session

    repository.mark_failed.side_effect = RuntimeError("cannot write failed state")

    with (
        app.app_context(),
        patch("app.services.background_crawl_runner." "db.session.rollback"),
    ):
        BackgroundCrawlRunner._recover_failed_session(
            repository=repository,
            session_id="abc",
            error=RuntimeError("crawl failure"),
        )


def test_recovery_truncates_large_error(
    app: Flask,
) -> None:
    repository = MagicMock()

    session = MagicMock(
        spec=CrawlSession,
    )

    repository.get.return_value = session

    with (
        app.app_context(),
        patch("app.services.background_crawl_runner." "db.session.rollback"),
    ):
        BackgroundCrawlRunner._recover_failed_session(
            repository=repository,
            session_id="abc",
            error=RuntimeError("x" * 10_000),
        )

    call = repository.mark_failed.call_args

    assert call is not None

    error_message = call.kwargs["error_message"]

    assert len(error_message) == 2000


def test_recovery_empty_error_uses_class_name(
    app: Flask,
) -> None:
    repository = MagicMock()

    session = MagicMock(
        spec=CrawlSession,
    )

    repository.get.return_value = session

    with (
        app.app_context(),
        patch("app.services.background_crawl_runner." "db.session.rollback"),
    ):
        BackgroundCrawlRunner._recover_failed_session(
            repository=repository,
            session_id="abc",
            error=RuntimeError(),
        )

    repository.mark_failed.assert_called_once_with(
        session=session,
        error_message="RuntimeError",
    )
