from __future__ import annotations

import logging

import flask.cli

from app import create_app
from app.config import Config

logger = logging.getLogger("app")


app = create_app()


if __name__ == "__main__":
    # Disable Flask's default startup banner.
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
