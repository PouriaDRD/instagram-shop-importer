from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


def _prepare_runtime_directory() -> Path:
    """
    Make runtime-relative paths stable.

    Development:
        project root

    PyInstaller:
        directory containing SeloraInstagramImporter.exe
    """

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


if __name__ == "__main__":
    flask.cli.show_server_banner = lambda *args, **kwargs: None

    logger.info(
        "Importer ready on http://%s:%s",
        Config.HOSTNAME,
        Config.PORT,
    )

    app.run(
        host=Config.HOSTNAME,
        port=Config.PORT,
        debug=Config.DEBUG,
        use_reloader=False,
    )
