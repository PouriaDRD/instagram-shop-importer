from __future__ import annotations

import logging
import sys
from typing import Final

LOG_FORMAT: Final[str] = "%(asctime)s  " "%(levelname)-6s " "%(name)-10s " "%(message)s"

DATE_FORMAT: Final[str] = "%H:%M:%S"


def configure_logging(
    *,
    level: str = "INFO",
) -> None:
    """
    Configure concise console logging for the importer.
    """

    normalized_level = level.strip().upper()

    numeric_level = getattr(
        logging,
        normalized_level,
        None,
    )

    if not isinstance(numeric_level, int):
        raise ValueError(f"Invalid log level: {level!r}")

    root_logger = logging.getLogger()

    root_logger.handlers.clear()
    root_logger.setLevel(numeric_level)

    handler = logging.StreamHandler(sys.stdout)

    handler.setFormatter(
        logging.Formatter(
            fmt=LOG_FORMAT,
            datefmt=DATE_FORMAT,
        )
    )

    root_logger.addHandler(handler)

    # We handle HTTP logging ourselves.
    werkzeug_logger = logging.getLogger("werkzeug")

    werkzeug_logger.handlers.clear()
    werkzeug_logger.propagate = False
    werkzeug_logger.setLevel(logging.ERROR)
