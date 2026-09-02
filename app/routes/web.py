from __future__ import annotations

import logging
from typing import cast

from flask import (
    Blueprint,
    Flask,
    abort,
    current_app,
    jsonify,
    render_template,
    request,
    url_for,
)
from flask.typing import ResponseReturnValue

from app.crawler.instagram import (
    PlaywrightInstagramProvider,
)
from app.repositories import (
    CrawlSessionRepository,
)
from app.services import (
    BackgroundCrawlRunner,
    CrawlService,
)

logger = logging.getLogger("app")


web_bp = Blueprint(
    "web",
    __name__,
)


@web_bp.get("/")
def index() -> str:
    return render_template("index.html")


@web_bp.get("/crawls")
def crawl_list() -> str:
    repository = CrawlSessionRepository()

    sessions = repository.list_all(limit=100)

    return render_template(
        "crawl_list.html",
        sessions=sessions,
    )


@web_bp.post("/crawl")
def start_crawl() -> ResponseReturnValue:
    username = (
        request.form.get(
            "username",
            "",
        )
        .strip()
        .lstrip("@")
    )

    if not username:
        return (
            jsonify(
                {
                    "error": "invalid_username",
                    "message": "نام کاربری اینستاگرام الزامی است.",
                }
            ),
            400,
        )

    raw_max_items = request.form.get(
        "max_items",
        "",
    ).strip()

    max_items: int | None = None

    if raw_max_items:
        try:
            max_items = int(raw_max_items)

        except ValueError:
            return (
                jsonify(
                    {
                        "error": "invalid_max_items",
                        "message": "تعداد محتوا باید یک عدد معتبر باشد.",
                    }
                ),
                400,
            )

        if max_items <= 0:
            return (
                jsonify(
                    {
                        "error": "invalid_max_items",
                        "message": "تعداد محتوا باید بیشتر از صفر باشد.",
                    }
                ),
                400,
            )

        if max_items > 100:
            return (
                jsonify(
                    {
                        "error": "invalid_max_items",
                        "message": "در حال حاضر حداکثر ۱۰۰ محتوا قابل دریافت است.",
                    }
                ),
                400,
            )

    service = CrawlService(
        provider=PlaywrightInstagramProvider(),
        repository=CrawlSessionRepository(),
    )

    try:
        session = service.create_session(
            username=username,
        )

    except Exception:
        logger.exception(
            "Failed to create crawl session for @%s",
            username,
        )

        return (
            jsonify(
                {
                    "error": "session_creation_failed",
                    "message": "ساخت نشست کراول با خطا مواجه شد.",
                }
            ),
            500,
        )

    # Safely cast current_app to explicit Flask instance for type checkers
    app = cast(Flask, current_app._get_current_object())  # type: ignore[attr-defined]

    runner = BackgroundCrawlRunner()

    runner.start(
        app=app,
        session_id=session.id,
        max_items=max_items,
    )

    return (
        jsonify(
            {
                "id": session.id,
                "username": session.username,
                "status": session.status,
                "status_url": url_for(
                    "web.crawl_status",
                    session_id=session.id,
                ),
                "detail_url": url_for(
                    "web.crawl_detail",
                    session_id=session.id,
                ),
            }
        ),
        202,
    )


@web_bp.get("/crawl/<session_id>/status")
def crawl_status(
    session_id: str,
) -> ResponseReturnValue:
    repository = CrawlSessionRepository()

    session = repository.get(session_id=session_id)

    if session is None:
        return (
            jsonify(
                {
                    "error": "not_found",
                    "message": "نشست کراول پیدا نشد.",
                }
            ),
            404,
        )

    return jsonify(
        {
            "id": session.id,
            "username": session.username,
            "status": session.status,
            "full_name": session.full_name,
            "crawled_media_count": session.crawled_media_count,
            "error_message": session.error_message,
            "detail_url": url_for(
                "web.crawl_detail",
                session_id=session.id,
            ),
        }
    )


@web_bp.get("/crawl/<session_id>")
def crawl_detail(
    session_id: str,
) -> ResponseReturnValue:
    repository = CrawlSessionRepository()

    session = repository.get(session_id=session_id)

    if session is None:
        abort(404)

    return render_template(
        "crawl_detail.html",
        session=session,
    )