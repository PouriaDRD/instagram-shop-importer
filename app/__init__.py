from __future__ import annotations

import logging
import time
from pathlib import Path

from flask import (
    Flask,
    Response,
    g,
    request,
)
from flask.typing import ResponseReturnValue
from werkzeug.exceptions import HTTPException

from app.common.datetime import (
    format_iran_datetime,
)
from app.common.logging import (
    configure_logging,
)
from app.config import Config
from app.extensions import db

logger = logging.getLogger("app")
http_logger = logging.getLogger("http")


def create_app() -> Flask:
    configure_logging(
        level=Config.LOG_LEVEL,
    )

    app_dir = Path(__file__).resolve().parent

    app = Flask(
        __name__,
        instance_relative_config=True,
        static_folder=str(app_dir / "static"),
        static_url_path="/static",
        template_folder=str(app_dir / "templates"),
    )

    app.config.from_object(Config)

    db.init_app(app)

    register_template_filters(app)

    register_routes(app)

    register_http_logging(app)

    register_error_handlers(app)

    with app.app_context():
        from app import models  # noqa: F401

        db.create_all()

    return app


def register_template_filters(
    app: Flask,
) -> None:
    app.jinja_env.filters["iran_datetime"] = format_iran_datetime


def register_routes(
    app: Flask,
) -> None:
    from app.routes.web import web_bp

    app.register_blueprint(web_bp)


def register_http_logging(
    app: Flask,
) -> None:
    @app.before_request
    def start_request_timer() -> None:
        g.request_started_at = time.perf_counter()

    @app.after_request
    def log_request(
        response: Response,
    ) -> Response:
        started_at: float | None = getattr(
            g,
            "request_started_at",
            None,
        )

        duration_ms = 0

        if started_at is not None:
            duration_ms = round((time.perf_counter() - started_at) * 1000)

        level = _http_log_level(response.status_code)

        http_logger.log(
            level,
            "%-3s  %-5s %-36s %s ms",
            response.status_code,
            request.method,
            request.path,
            duration_ms,
        )

        return response


def register_error_handlers(
    app: Flask,
) -> None:
    @app.errorhandler(Exception)
    def handle_unexpected_error(
        error: Exception,
    ) -> ResponseReturnValue:
        if isinstance(
            error,
            HTTPException,
        ):
            return error

        logger.exception("Unhandled application error")

        return (
            {
                "error": "internal_server_error",
                "message": ("Unexpected application error."),
            },
            500,
        )


def _http_log_level(
    status_code: int,
) -> int:
    if status_code >= 500:
        return logging.ERROR

    if status_code >= 400:
        return logging.WARNING

    return logging.INFO
