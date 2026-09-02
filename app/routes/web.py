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

from app.crawler.instagram import PlaywrightInstagramProvider
from app.repositories import CrawlSessionRepository, ImportDraftRepository
from app.services import BackgroundCrawlRunner, CrawlService
from app.services.import_draft_service import ImportDraftItemUpdate, ImportDraftService

logger = logging.getLogger("app")

web_bp = Blueprint("web", __name__)


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
    return render_template("crawl_list.html", sessions=sessions)


@web_bp.get("/crawl")
@web_bp.get("/crawl/")
def crawl_get_redirect() -> ResponseReturnValue:
    return redirect(url_for("web.index"))


@web_bp.post("/crawl")
def start_crawl() -> ResponseReturnValue:
    username = request.form.get("username", "").strip().lstrip("@")

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

    raw_max_items = request.form.get("max_items", "").strip()
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
        crawl_session = service.create_session(username=username)
    except Exception:
        logger.exception("Failed to create crawl session for @%s", username)
        return (
            jsonify(
                {
                    "error": "session_creation_failed",
                    "message": "ساخت نشست کراول با خطا مواجه شد.",
                }
            ),
            500,
        )

    flask_app = cast(Flask, current_app._get_current_object())
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
                "username": crawl_session.username,
                "status": crawl_session.status,
                "status_url": url_for(
                    "web.crawl_status",
                    session_id=crawl_session.id,
                ),
                "detail_url": url_for(
                    "web.crawl_detail",
                    session_id=crawl_session.id,
                ),
            }
        ),
        202,
    )


@web_bp.get("/crawl/<session_id>/status")
def crawl_status(session_id: str) -> ResponseReturnValue:
    repository = CrawlSessionRepository()
    crawl_session = repository.get(session_id=session_id)

    if crawl_session is None:
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
            "id": crawl_session.id,
            "username": crawl_session.username,
            "status": crawl_session.status,
            "full_name": crawl_session.full_name,
            "crawled_media_count": crawl_session.crawled_media_count,
            "error_message": crawl_session.error_message,
            "detail_url": url_for(
                "web.crawl_detail",
                session_id=crawl_session.id,
            ),
        }
    )


@web_bp.get("/crawl/<session_id>")
def crawl_detail(session_id: str) -> ResponseReturnValue:
    repository = CrawlSessionRepository()
    crawl_session = repository.get(session_id=session_id)

    if crawl_session is None:
        abort(404)

    return render_template(
        "crawl_detail.html",
        crawl_session=crawl_session,
        draft_error=None,
    )


@web_bp.post("/crawl/<session_id>/draft")
def create_import_draft(session_id: str) -> ResponseReturnValue:
    crawl_repository = CrawlSessionRepository()
    crawl_session = crawl_repository.get(session_id=session_id)

    if crawl_session is None:
        abort(404)

    selected_media_ids = set(request.form.getlist("media_ids"))
    selected_asset_ids = set(request.form.getlist("asset_ids"))
    service = ImportDraftService(repository=ImportDraftRepository())

    try:
        draft = service.create_from_session(
            crawl_session=crawl_session,
            selected_media_ids=selected_media_ids,
            selected_asset_ids=selected_asset_ids,
        )
    except ValueError as exc:
        return (
            render_template(
                "crawl_detail.html",
                crawl_session=crawl_session,
                draft_error=str(exc),
            ),
            400,
        )
    except Exception:
        logger.exception("Failed to create import draft from crawl %s", session_id)
        return (
            render_template(
                "crawl_detail.html",
                crawl_session=crawl_session,
                draft_error="ساخت پیش‌نویس با خطا مواجه شد. دوباره تلاش کنید.",
            ),
            500,
        )

    return redirect(url_for("web.import_draft_review", draft_id=draft.id))


@web_bp.get("/draft/<draft_id>")
def import_draft_review(draft_id: str) -> ResponseReturnValue:
    repository = ImportDraftRepository()
    draft = repository.get(draft_id=draft_id)

    if draft is None:
        abort(404)

    service = ImportDraftService(repository=repository)
    service.ensure_product_data(draft=draft)

    # Reload after potential creation so all relationships are consistently available.
    draft = repository.get(draft_id=draft_id)
    if draft is None:
        abort(404)

    return render_template(
        "import_review.html",
        draft=draft,
        save_error=None,
        save_success=request.args.get("saved") == "1",
    )


@web_bp.post("/draft/<draft_id>/save")
def save_import_draft(draft_id: str) -> ResponseReturnValue:
    repository = ImportDraftRepository()
    draft = repository.get(draft_id=draft_id)

    if draft is None:
        abort(404)

    updates: list[ImportDraftItemUpdate] = []

    try:
        for item in draft.items:
            updates.append(
                ImportDraftItemUpdate(
                    item_id=item.id,
                    is_selected=item.id in set(request.form.getlist("selected_item_ids")),
                    product_name=request.form.get(f"product_name__{item.id}", "").strip(),
                    description=request.form.get(f"description__{item.id}", "").strip(),
                    sale_price=_parse_optional_int(
                        request.form.get(f"sale_price__{item.id}", ""),
                        label="قیمت فروش",
                    ),
                    list_price=_parse_optional_int(
                        request.form.get(f"list_price__{item.id}", ""),
                        label="قیمت قبل از تخفیف",
                    ),
                    stock=_parse_required_int(
                        request.form.get(f"stock__{item.id}", "0"),
                        label="موجودی",
                    ),
                    colors=_split_values(request.form.get(f"colors__{item.id}", "")),
                    sizes=_split_values(request.form.get(f"sizes__{item.id}", "")),
                    primary_asset_id=(
                        request.form.get(f"primary_asset__{item.id}", "").strip()
                        or None
                    ),
                )
            )

        service = ImportDraftService(repository=repository)
        service.update_draft(draft=draft, updates=updates)
        submit_action = request.form.get("submit_action", "save").strip()
    except ValueError as exc:
        refreshed_draft = repository.get(draft_id=draft_id) or draft
        return (
            render_template(
                "import_review.html",
                draft=refreshed_draft,
                save_error=str(exc),
                save_success=False,
            ),
            400,
        )
    except Exception:
        logger.exception("Failed to save import draft %s", draft_id)
        refreshed_draft = repository.get(draft_id=draft_id) or draft
        return (
            render_template(
                "import_review.html",
                draft=refreshed_draft,
                save_error="ذخیره پیش‌نویس با خطا مواجه شد. دوباره تلاش کنید.",
                save_success=False,
            ),
            500,
        )

    if submit_action == "review":
        return redirect(url_for("web.import_draft_final_review", draft_id=draft_id))

    return redirect(url_for("web.import_draft_review", draft_id=draft_id, saved=1))


@web_bp.get("/draft/<draft_id>/review")
def import_draft_final_review(draft_id: str) -> ResponseReturnValue:
    repository = ImportDraftRepository()
    draft = repository.get(draft_id=draft_id)

    if draft is None:
        abort(404)

    service = ImportDraftService(repository=repository)
    service.ensure_product_data(draft=draft)

    draft = repository.get(draft_id=draft_id)
    if draft is None:
        abort(404)

    return render_template(
        "import_final_review.html",
        draft=draft,
    )


def _parse_optional_int(raw_value: str, *, label: str) -> int | None:
    normalized = _normalize_numeric_input(raw_value)
    if not normalized:
        return None
    try:
        return int(normalized)
    except ValueError as exc:
        raise ValueError(f"{label} باید یک عدد معتبر باشد.") from exc


def _parse_required_int(raw_value: str, *, label: str) -> int:
    normalized = _normalize_numeric_input(raw_value)
    if not normalized:
        return 0
    try:
        return int(normalized)
    except ValueError as exc:
        raise ValueError(f"{label} باید یک عدد معتبر باشد.") from exc


def _normalize_numeric_input(value: str) -> str:
    translation = str.maketrans("۰۱۲۳۴۵۶۷۸۹٬،", "0123456789,,")
    return value.strip().translate(translation).replace(",", "").replace(" ", "")


def _split_values(value: str) -> tuple[str, ...]:
    normalized = value.replace("،", ",")
    return tuple(part.strip() for part in normalized.split(",") if part.strip())
