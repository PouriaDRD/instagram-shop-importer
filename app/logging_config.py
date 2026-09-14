from __future__ import annotations

import atexit
import faulthandler
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import platform
import sys
import threading


_CONFIGURED = False
_CRASH_HANDLE = None


class _LoggerNameFilter(logging.Filter):
    def __init__(
        self,
        *,
        exact: tuple[str, ...] = (),
        prefixes: tuple[str, ...] = (),
    ) -> None:
        super().__init__()
        self.exact = exact
        self.prefixes = prefixes

    def filter(
        self,
        record: logging.LogRecord,
    ) -> bool:
        name = record.name

        if name in self.exact:
            return True

        return any(
            name.startswith(prefix)
            for prefix in self.prefixes
        )


class _ExcludeLoggerFilter(logging.Filter):
    def __init__(
        self,
        *,
        exact: tuple[str, ...] = (),
        prefixes: tuple[str, ...] = (),
    ) -> None:
        super().__init__()
        self.exact = exact
        self.prefixes = prefixes

    def filter(
        self,
        record: logging.LogRecord,
    ) -> bool:
        name = record.name

        if name in self.exact:
            return False

        return not any(
            name.startswith(prefix)
            for prefix in self.prefixes
        )


def _application_root() -> Path:
    if getattr(
        sys,
        "frozen",
        False,
    ):
        return Path(
            sys.executable
        ).resolve().parent

    return Path(
        __file__
    ).resolve().parents[1]


def get_log_directory() -> Path:
    path = (
        _application_root()
        / "logs"
    )

    path.mkdir(
        parents=True,
        exist_ok=True,
    )

    return path


def _file_handler(
    *,
    path: Path,
    level: int = logging.DEBUG,
) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        path,
        maxBytes=10 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
        delay=True,
    )

    handler.setLevel(
        level
    )

    handler.setFormatter(
        logging.Formatter(
            (
                "%(asctime)s.%(msecs)03d "
                "%(levelname)-8s "
                "%(name)s "
                "[pid=%(process)d thread=%(threadName)s] "
                "%(message)s"
            ),
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    return handler


def _install_crash_logging(
    log_directory: Path,
) -> None:
    global _CRASH_HANDLE

    crash_path = (
        log_directory
        / "crash.log"
    )

    _CRASH_HANDLE = crash_path.open(
        "a",
        encoding="utf-8",
        buffering=1,
    )

    try:
        faulthandler.enable(
            file=_CRASH_HANDLE,
            all_threads=True,
        )
    except Exception:
        logging.getLogger(
            __name__
        ).exception(
            "Could not enable faulthandler."
        )

    def close_crash_handle() -> None:
        global _CRASH_HANDLE

        if _CRASH_HANDLE is None:
            return

        try:
            _CRASH_HANDLE.flush()
            _CRASH_HANDLE.close()
        except Exception:
            pass

        _CRASH_HANDLE = None

    atexit.register(
        close_crash_handle
    )


def _install_exception_hooks() -> None:
    previous_sys_hook = (
        sys.excepthook
    )

    def sys_hook(
        exc_type,
        exc_value,
        exc_traceback,
    ) -> None:
        if issubclass(
            exc_type,
            KeyboardInterrupt,
        ):
            previous_sys_hook(
                exc_type,
                exc_value,
                exc_traceback,
            )
            return

        logging.getLogger(
            "app.crash"
        ).critical(
            "Uncaught exception",
            exc_info=(
                exc_type,
                exc_value,
                exc_traceback,
            ),
        )

    sys.excepthook = sys_hook

    if hasattr(
        threading,
        "excepthook",
    ):
        def thread_hook(
            args,
        ) -> None:
            logging.getLogger(
                "app.crash"
            ).critical(
                (
                    "Uncaught thread exception: "
                    "thread=%s"
                ),
                getattr(
                    args.thread,
                    "name",
                    None,
                ),
                exc_info=(
                    args.exc_type,
                    args.exc_value,
                    args.exc_traceback,
                ),
            )

        threading.excepthook = (
            thread_hook
        )


def configure_logging() -> Path:
    global _CONFIGURED

    log_directory = (
        get_log_directory()
    )

    if _CONFIGURED:
        return log_directory

    root_logger = (
        logging.getLogger()
    )

    root_logger.setLevel(
        logging.DEBUG
    )

    for handler in tuple(
        root_logger.handlers
    ):
        root_logger.removeHandler(
            handler
        )

        try:
            handler.close()
        except Exception:
            pass

    formatter = logging.Formatter(
        (
            "%(asctime)s "
            "%(levelname)-7s "
            "%(name)-12s "
            "%(message)s"
        ),
        datefmt="%H:%M:%S",
    )

    console_handler = (
        logging.StreamHandler()
    )
    console_handler.setLevel(
        logging.INFO
    )
    console_handler.setFormatter(
        formatter
    )

    root_logger.addHandler(
        console_handler
    )

    # HTTP-only logs
    http_handler = _file_handler(
        path=(
            log_directory
            / "http.log"
        ),
    )
    http_handler.addFilter(
        _LoggerNameFilter(
            exact=("http",),
            prefixes=(
                "app.http",
            ),
        )
    )
    root_logger.addHandler(
        http_handler
    )

    # Instagram crawling / local media logs
    crawler_handler = (
        _file_handler(
            path=(
                log_directory
                / "crawler.log"
            ),
        )
    )
    crawler_handler.addFilter(
        _LoggerNameFilter(
            exact=("crawler",),
            prefixes=(
                "app.crawler",
                "app.services.instagram",
                "app.integrations.instagram",
            ),
        )
    )
    root_logger.addHandler(
        crawler_handler
    )

    # Persistent Instagram media / derivative logs
    media_handler = _file_handler(
        path=(
            log_directory
            / "media.log"
        ),
    )
    media_handler.addFilter(
        _LoggerNameFilter(
            prefixes=(
                "app.services.media_storage_service",
                "app.services.selora_media_derivative_service",
            ),
        )
    )
    root_logger.addHandler(
        media_handler
    )

    # Draft / workspace lifecycle logs
    draft_handler = _file_handler(
        path=(
            log_directory
            / "draft.log"
        ),
    )
    draft_handler.addFilter(
        _LoggerNameFilter(
            prefixes=(
                "app.services.import_workspace_service",
                "app.services.remote_workspace_coordinator",
            ),
        )
    )
    root_logger.addHandler(
        draft_handler
    )

    # Selora integration / transfer logs
    selora_handler = (
        _file_handler(
            path=(
                log_directory
                / "selora.log"
            ),
        )
    )
    selora_handler.addFilter(
        _LoggerNameFilter(
            prefixes=(
                "app.integrations.selora",
            ),
        )
    )
    root_logger.addHandler(
        selora_handler
    )

    # Selora asset upload / resumable checkpoint logs
    upload_handler = _file_handler(
        path=(
            log_directory
            / "upload.log"
        ),
    )
    upload_handler.addFilter(
        _LoggerNameFilter(
            prefixes=(
                "app.services.selora_import_service",
                "app.services.selora_upload_checkpoint_service",
            ),
        )
    )
    root_logger.addHandler(
        upload_handler
    )

    # General application log.
    # HTTP/crawler/Selora events remain in their own files.
    app_handler = _file_handler(
        path=(
            log_directory
            / "app.log"
        ),
    )
    app_handler.addFilter(
        _ExcludeLoggerFilter(
            exact=(
                "http",
                "crawler",
            ),
            prefixes=(
                "app.http",
                "app.crawler",
                "app.services.instagram",
                "app.integrations.instagram",
                "app.integrations.selora",
                "app.services.selora",
            ),
        )
    )
    root_logger.addHandler(
        app_handler
    )

    # One consolidated warning/error log.
    error_handler = _file_handler(
        path=(
            log_directory
            / "errors.log"
        ),
        level=logging.WARNING,
    )
    root_logger.addHandler(
        error_handler
    )

    _install_crash_logging(
        log_directory
    )
    _install_exception_hooks()

    _CONFIGURED = True

    logger = logging.getLogger(
        "app"
    )

    logger.info(
        (
            "Logging initialized: "
            "directory=%s frozen=%s "
            "python=%s platform=%s "
            "cwd=%s executable=%s"
        ),
        log_directory,
        bool(
            getattr(
                sys,
                "frozen",
                False,
            )
        ),
        platform.python_version(),
        platform.platform(),
        os.getcwd(),
        sys.executable,
    )

    return log_directory
