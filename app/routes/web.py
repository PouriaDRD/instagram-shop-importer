from __future__ import annotations

import logging

from flask import (
    Blueprint,
    Response,
    render_template,
    request,
)

logger = logging.getLogger("crawler")


web_bp = Blueprint(
    "web",
    __name__,
)


@web_bp.get("/")
def index() -> str:
    return render_template("index.html")


@web_bp.post("/crawl")
def start_crawl() -> Response:
    username = (
        request.form.get(
            "username",
            "",
        )
        .strip()
        .lstrip("@")
    )

    if not username:
        logger.warning("Crawl rejected: username is empty")

        return Response(
            "Instagram username is required.",
            status=400,
            content_type=("text/plain; charset=utf-8"),
        )

    logger.info(
        "Crawl started for @%s",
        username,
    )

    return Response(
        ("Crawl request received for " f"@{username}"),
        status=200,
        content_type=("text/plain; charset=utf-8"),
    )
