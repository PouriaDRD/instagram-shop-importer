from __future__ import annotations

import logging
from typing import cast

from flask import (
    Blueprint,
    Flask,
    abort,
    current_app,
    jsonify,
    redirect,
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


@web_bp.get("/favicon.ico")
def favicon() -> ResponseReturnValue:
    return current_app.send_static_file("images/favicon.ico")


@web_bp.get("/crawls")
def crawl_list() -> str:
    repository = CrawlSessionRepository()

    sessions = repository.list_all(limit=100)

    return render_template(
        "crawl_list.html",
        sessions=sessions,
    )


@web_bp.get("/crawl")
@web_bp.get("/crawl/")
def crawl_get_redirect() -> ResponseReturnValue:
    return redirect(url_for("web.index"))


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
                    "message": ("نام کاربری اینستاگرام " "الزامی است."),
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
                        "message": ("تعداد محتوا باید " "یک عدد معتبر باشد."),
                    }
                ),
                400,
            )

        if max_items <= 0:
            return (
                jsonify(
                    {
                        "error": "invalid_max_items",
                        "message": ("تعداد محتوا باید " "بیشتر از صفر باشد."),
                    }
                ),
                400,
            )

        if max_items > 100:
            return (
                jsonify(
                    {
                        "error": "invalid_max_items",
                        "message": ("در حال حاضر حداکثر " "۱۰۰ محتوا قابل دریافت است."),
                    }
                ),
                400,
            )

    service = CrawlService(
        provider=(PlaywrightInstagramProvider()),
        repository=(CrawlSessionRepository()),
    )

    try:
        crawl_session = service.create_session(
            username=username,
        )

    except Exception:
        logger.exception(
            ("Failed to create crawl " "session for @%s"),
            username,
        )

        return (
            jsonify(
                {
                    "error": ("session_creation_failed"),
                    "message": ("ساخت نشست کراول " "با خطا مواجه شد."),
                }
            ),
            500,
        )

    flask_app = cast(
        Flask,
        current_app._get_current_object(), # type: ignore
    )

    runner = BackgroundCrawlRunner()

    runner.start(
        app=flask_app,
        session_id=crawl_session.id,
        max_items=max_items,
    )

    return (
        jsonify(
            {
                "id": crawl_session.id,
                "username": (crawl_session.username),
                "status": (crawl_session.status),
                "status_url": url_for(
                    "web.crawl_status",
                    session_id=(crawl_session.id),
                ),
                "detail_url": url_for(
                    "web.crawl_detail",
                    session_id=(crawl_session.id),
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

    crawl_session = repository.get(session_id=session_id)

    if crawl_session is None:
        return (
            jsonify(
                {
                    "error": "not_found",
                    "message": ("نشست کراول پیدا نشد."),
                }
            ),
            404,
        )

    return jsonify(
        {
            "id": crawl_session.id,
            "username": (crawl_session.username),
            "status": crawl_session.status,
            "full_name": (crawl_session.full_name),
            "crawled_media_count": (crawl_session.crawled_media_count),
            "error_message": (crawl_session.error_message),
            "detail_url": url_for(
                "web.crawl_detail",
                session_id=crawl_session.id,
            ),
        }
    )


@web_bp.get("/crawl/<session_id>")
def crawl_detail(
    session_id: str,
) -> ResponseReturnValue:
    repository = CrawlSessionRepository()

    crawl_session = repository.get(session_id=session_id)

    if crawl_session is None:
        abort(404)

    return render_template(
        "crawl_detail.html",
        crawl_session=crawl_session,
    )
