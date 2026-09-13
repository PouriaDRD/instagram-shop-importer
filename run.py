from __future__ import annotations

import logging
import os
import sys
import threading
import webbrowser
from pathlib import Path


def _prepare_runtime_directory() -> Path:
    if getattr(sys, "frozen", False):
        runtime_root = Path(sys.executable).resolve().parent
    else:
        runtime_root = Path(__file__).resolve().parent

    os.chdir(runtime_root)
    return runtime_root


RUNTIME_ROOT = _prepare_runtime_directory()

import flask.cli  # noqa: E402

from app import create_app  # noqa: E402
from app.config import Config  # noqa: E402

logger = logging.getLogger("app")

app = create_app()


def _open_browser() -> None:
    url = f"http://{Config.HOSTNAME}:{Config.PORT}"

    try:
        webbrowser.open(url)
    except Exception:
        logger.exception("Could not open browser automatically.")


if __name__ == "__main__":
    flask.cli.show_server_banner = lambda *args, **kwargs: None

    url = f"http://{Config.HOSTNAME}:" f"{Config.PORT}"

    logger.info(
        "Importer ready on %s",
        url,
    )

    threading.Timer(
        1.0,
        _open_browser,
    ).start()

    app.run(
        host=Config.HOSTNAME,
        port=Config.PORT,
        debug=Config.DEBUG,
        use_reloader=False,
    )
