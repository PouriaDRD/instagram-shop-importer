from __future__ import annotations

from dataclasses import dataclass
import logging

from flask import (
    Blueprint,
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
from app.integrations.selora.client import (
    SeloraApiClient,
    SeloraApiError,
    SeloraApiResponseError,
)
from app.integrations.selora.payload_mapper import (
    SeloraPayloadMapper,
    SeloraPayloadMappingError,
)
from app.services.selora_import_service import SeloraImportService
from app.services.client_instance_identity_service import (
    ClientInstanceIdentityService,
)
from app.services.remote_workspace_coordinator import (
    RemoteWorkspaceCoordinator,
    RemoteWorkspaceStateError,
)
from app.services.import_validation_service import (
    ImportDraftValidationService,
)

logger = logging.getLogger("app")

web_bp = Blueprint("web", __name__)


def _selora_client() -> SeloraApiClient:
    return SeloraApiClient(
        base_url=current_app.config[
            "SELORA_API_BASE_URL"
        ],
        api_key=current_app.config[
            "SELORA_API_KEY"
        ],
        connect_timeout_seconds=current_app.config[
            "SELORA_API_CONNECT_TIMEOUT_SECONDS"
        ],
        read_timeout_seconds=current_app.config[
            "SELORA_API_READ_TIMEOUT_SECONDS"
        ],
    )


def _client_instance_id() -> str:
    return ClientInstanceIdentityService(
        path=current_app.config[
            "CLIENT_INSTANCE_ID_FILE"
        ],
    ).get_or_create()


def _remote_coordinator(
    *,
    repository: ImportDraftRepository,
) -> RemoteWorkspaceCoordinator:
    return RemoteWorkspaceCoordinator(
        client=_selora_client(),
        repository=repository,
        client_instance_id=(
            _client_instance_id()
        ),
    )


@dataclass(frozen=True, slots=True)
class RemoteEditorState:
    error: str | None
    read_only_reason: str | None
    retry_allowed: bool


def _remote_error_message(
    exc: SeloraApiError,
) -> tuple[str, str | None, bool]:
    if isinstance(
        exc,
        SeloraApiResponseError,
    ):
        if exc.code == "workspace_locked":
            return (
                "این Workspace در حال حاضر توسط اپراتور دیگری در حال ویرایش است.",
                "قفل ویرایش در اختیار اپراتور دیگری است.",
                True,
            )

        if exc.code == "workspace_finalized":
            return (
                "این Workspace در سلورا نهایی شده و دیگر قابل ویرایش نیست.",
                "وضعیت این Workspace در سلورا نهایی و فقط‌خواندنی است.",
                False,
            )

        if exc.code == "revision_conflict":
            return (
                "نسخه جدیدتری از این Workspace در سلورا ثبت شده است. صفحه را تازه‌سازی کن تا آخرین وضعیت دریافت شود.",
                "نسخه محلی از Selora عقب‌تر است.",
                True,
            )

        if exc.code == "invalid_workspace_lock":
            return (
                "قفل ویرایش این Workspace منقضی شده یا دیگر معتبر نیست.",
                "قفل ویرایش این اپراتور معتبر نیست.",
                True,
            )

    return (
        str(exc),
        "ارتباط امن با Workspace سلورا تأیید نشد.",
        True,
    )


def _prepare_remote_editor_state(
    *,
    draft,
    crawl_session,
    repository: ImportDraftRepository,
) -> RemoteEditorState:
    try:
        state = _remote_coordinator(
            repository=repository,
        ).resolve_and_acquire(
            workspace=draft,
            instagram_username=(
                crawl_session.username
            ),
        )

        if not state.is_editable:
            return RemoteEditorState(
                error=None,
                read_only_reason=(
                    "وضعیت این Workspace در سلورا نهایی و فقط‌خواندنی است."
                ),
                retry_allowed=False,
            )

        return RemoteEditorState(
            error=None,
            read_only_reason=None,
            retry_allowed=False,
        )

    except SeloraApiError as exc:
        message, reason, retry_allowed = (
            _remote_error_message(
                exc
            )
        )

        if not (
            isinstance(
                exc,
                SeloraApiResponseError,
            )
            and exc.status_code in {
                409,
                423,
            }
        ):
            logger.exception(
                "Remote workspace preparation failed for %s",
                draft.id,
            )

        return RemoteEditorState(
            error=message,
            read_only_reason=reason,
            retry_allowed=retry_allowed,
        )


def _remote_api_error_response(
    *,
    exc: SeloraApiError,
) -> ResponseReturnValue:
    if isinstance(
        exc,
        SeloraApiResponseError,
    ):
        status_code = (
            exc.status_code
            if exc.status_code in {
                409,
                423,
            }
            else 502
        )
        code = exc.code
    else:
        status_code = 503
        code = "remote_workspace_unavailable"

    message, reason, retry_allowed = (
        _remote_error_message(
            exc
        )
    )

    return (
        jsonify(
            {
                "ok": False,
                "error": code,
                "message": message,
                "read_only_reason": reason,
                "retry_allowed": retry_allowed,
            }
        ),
        status_code,
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

    flask_app = current_app.app_context().app
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


def _render_crawl_detail(
    *,
    crawl_session,
    draft_error: str | None = None,
    status_code: int = 200,
) -> ResponseReturnValue:
    draft_repository = ImportDraftRepository()
    current_draft = draft_repository.get_current_for_session(
        crawl_session_id=crawl_session.id
    )

    if current_draft is None:
        selected_media_ids = {media.id for media in crawl_session.media}
        selected_asset_ids = {
            asset.id for media in crawl_session.media for asset in media.assets
        }
    else:
        selected_media_ids = {
            item.crawled_media_id for item in current_draft.items if item.is_selected
        }
        selected_asset_ids = {
            selected_asset.crawled_asset_id
            for item in current_draft.items
            if item.is_selected
            for selected_asset in item.selected_assets
            if selected_asset.is_selected
        }

    rendered = render_template(
        "crawl_detail.html",
        crawl_session=crawl_session,
        draft_error=draft_error,
        current_draft=current_draft,
        selected_media_ids=selected_media_ids,
        selected_asset_ids=selected_asset_ids,
    )

    if status_code == 200:
        return rendered

    return rendered, status_code


@web_bp.get("/crawl/<session_id>")
def crawl_detail(session_id: str) -> ResponseReturnValue:
    repository = CrawlSessionRepository()
    crawl_session = repository.get(session_id=session_id)

    if crawl_session is None:
        abort(404)

    return _render_crawl_detail(crawl_session=crawl_session)


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
        draft = service.create_or_update_from_session(
            crawl_session=crawl_session,
            selected_media_ids=selected_media_ids,
            selected_asset_ids=selected_asset_ids,
        )

    except ValueError as exc:
        return _render_crawl_detail(
            crawl_session=crawl_session,
            draft_error=str(exc),
            status_code=400,
        )

    except Exception:
        logger.exception(
            "Failed to synchronize import draft from crawl %s",
            session_id,
        )

        return _render_crawl_detail(
            crawl_session=crawl_session,
            draft_error=("به‌روزرسانی پیش‌نویس با خطا مواجه شد. " "دوباره تلاش کنید."),
            status_code=500,
        )

    return redirect(
        url_for(
            "web.import_draft_review",
            draft_id=draft.id,
        )
    )


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

    crawl_repository = CrawlSessionRepository()
    crawl_session = crawl_repository.get(
        session_id=draft.crawl_session_id
    )

    if crawl_session is None:
        abort(404)

    remote_state = _prepare_remote_editor_state(
        draft=draft,
        crawl_session=crawl_session,
        repository=repository,
    )

    draft = (
        repository.get(
            draft_id=draft_id
        )
        or draft
    )

    return render_template(
        "import_review.html",
        draft=draft,
        save_error=None,
        save_success=request.args.get("saved") == "1",
        remote_error=remote_state.error,
        remote_read_only=(
            draft.is_remote_read_only
            or remote_state.read_only_reason
            is not None
        ),
        remote_read_only_reason=(
            remote_state.read_only_reason
        ),
        remote_retry_allowed=(
            remote_state.retry_allowed
        ),
        heartbeat_seconds=current_app.config[
            "SELORA_WORKSPACE_HEARTBEAT_SECONDS"
        ],
    )


@web_bp.post("/draft/<draft_id>/item/<item_id>/autosave")
def autosave_import_draft_item(
    draft_id: str,
    item_id: str,
) -> ResponseReturnValue:
    repository = ImportDraftRepository()
    draft = repository.get(draft_id=draft_id)

    if draft is None:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "draft_not_found",
                    "message": "پیش‌نویس پیدا نشد.",
                }
            ),
            404,
        )

    item = next(
        (draft_item for draft_item in draft.items if draft_item.id == item_id),
        None,
    )

    if item is None:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "item_not_found",
                    "message": "محصول موردنظر در این پیش‌نویس پیدا نشد.",
                }
            ),
            404,
        )

    try:
        _remote_coordinator(
            repository=repository,
        ).ensure_mutation_allowed(
            workspace=draft,
        )

        update = ImportDraftItemUpdate(
            item_id=item.id,
            is_selected=(
                request.form.get(
                    "is_selected",
                    "",
                )
                == "1"
            ),
            product_name=request.form.get(
                "product_name",
                "",
            ).strip(),
            description=request.form.get(
                "description",
                "",
            ).strip(),
            sale_price=_parse_optional_int(
                request.form.get(
                    "sale_price",
                    "",
                ),
                label="قیمت فروش",
            ),
            list_price=_parse_optional_int(
                request.form.get(
                    "list_price",
                    "",
                ),
                label="قیمت قبل از تخفیف",
            ),
            stock=_parse_required_int(
                request.form.get(
                    "stock",
                    "0",
                ),
                label="موجودی",
            ),
            colors=_split_values(
                request.form.get(
                    "colors",
                    "",
                )
            ),
            sizes=_split_values(
                request.form.get(
                    "sizes",
                    "",
                )
            ),
            primary_asset_id=(
                request.form.get(
                    "primary_asset_id",
                    "",
                ).strip()
                or None
            ),
        )

        service = ImportDraftService(repository=repository)
        service.update_draft(
            draft=draft,
            updates=[
                update,
            ],
        )

    except ValueError as exc:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "invalid_item_data",
                    "message": str(exc),
                }
            ),
            400,
        )

    except RemoteWorkspaceStateError as exc:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "remote_workspace_read_only",
                    "message": str(exc),
                    "read_only_reason": str(exc),
                    "retry_allowed": True,
                }
            ),
            423,
        )

    except SeloraApiError as exc:
        return _remote_api_error_response(
            exc=exc
        )

    except Exception:
        logger.exception(
            ("Failed to autosave draft item %s " "in draft %s"),
            item_id,
            draft_id,
        )

        return (
            jsonify(
                {
                    "ok": False,
                    "error": "autosave_failed",
                    "message": ("ذخیره خودکار انجام نشد. " "دوباره تلاش کنید."),
                }
            ),
            500,
        )

    refreshed_draft = repository.get(draft_id=draft_id)

    updated_at = (
        refreshed_draft.updated_at.isoformat() if refreshed_draft is not None else None
    )

    return jsonify(
        {
            "ok": True,
            "draft_id": draft_id,
            "item_id": item_id,
            "updated_at": updated_at,
        }
    )


@web_bp.post("/draft/<draft_id>/save")
def save_import_draft(draft_id: str) -> ResponseReturnValue:
    repository = ImportDraftRepository()
    draft = repository.get(draft_id=draft_id)

    if draft is None:
        abort(404)

    updates: list[ImportDraftItemUpdate] = []

    try:
        _remote_coordinator(
            repository=repository,
        ).ensure_mutation_allowed(
            workspace=draft,
        )

        selected_item_ids = set(
            request.form.getlist(
                "selected_item_ids"
            )
        )

        rendered_items = [
            item
            for item in draft.items
            if item.is_selected
        ]

        for item in rendered_items:
            updates.append(
                ImportDraftItemUpdate(
                    item_id=item.id,
                    is_selected=(
                        item.id
                        in selected_item_ids
                    ),
                    product_name=request.form.get(
                        f"product_name__{item.id}", ""
                    ).strip(),
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
                remote_error=None,
                remote_read_only=(
                    refreshed_draft.is_remote_read_only
                ),
                remote_read_only_reason=None,
                remote_retry_allowed=False,
                heartbeat_seconds=current_app.config[
                    "SELORA_WORKSPACE_HEARTBEAT_SECONDS"
                ],
            ),
            400,
        )
    except RemoteWorkspaceStateError as exc:
        refreshed_draft = repository.get(draft_id=draft_id) or draft
        return (
            render_template(
                "import_review.html",
                draft=refreshed_draft,
                save_error=None,
                save_success=False,
                remote_error=str(exc),
                remote_read_only=True,
                remote_read_only_reason=str(exc),
                remote_retry_allowed=True,
                heartbeat_seconds=current_app.config[
                    "SELORA_WORKSPACE_HEARTBEAT_SECONDS"
                ],
            ),
            423,
        )
    except SeloraApiError as exc:
        refreshed_draft = repository.get(draft_id=draft_id) or draft
        message, reason, retry_allowed = (
            _remote_error_message(
                exc
            )
        )
        return (
            render_template(
                "import_review.html",
                draft=refreshed_draft,
                save_error=None,
                save_success=False,
                remote_error=message,
                remote_read_only=True,
                remote_read_only_reason=reason,
                remote_retry_allowed=retry_allowed,
                heartbeat_seconds=current_app.config[
                    "SELORA_WORKSPACE_HEARTBEAT_SECONDS"
                ],
            ),
            (
                exc.status_code
                if isinstance(
                    exc,
                    SeloraApiResponseError,
                )
                and exc.status_code in {
                    409,
                    423,
                }
                else 503
            ),
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
                remote_error=None,
                remote_read_only=(
                    refreshed_draft.is_remote_read_only
                ),
                remote_read_only_reason=None,
                remote_retry_allowed=False,
                heartbeat_seconds=current_app.config[
                    "SELORA_WORKSPACE_HEARTBEAT_SECONDS"
                ],
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

    crawl_repository = CrawlSessionRepository()
    crawl_session = crawl_repository.get(
        session_id=draft.crawl_session_id
    )

    if crawl_session is None:
        abort(404)

    remote_state = _prepare_remote_editor_state(
        draft=draft,
        crawl_session=crawl_session,
        repository=repository,
    )

    draft = (
        repository.get(
            draft_id=draft_id
        )
        or draft
    )

    validation = ImportDraftValidationService().validate(draft=draft)

    return render_template(
        "import_final_review.html",
        draft=draft,
        validation=validation,
        send_result=None,
        send_error=None,
        send_request_id="",
        remote_error=remote_state.error,
        remote_read_only=(
            draft.is_remote_read_only
            or remote_state.read_only_reason
            is not None
        ),
        remote_read_only_reason=(
            remote_state.read_only_reason
        ),
        remote_retry_allowed=(
            remote_state.retry_allowed
        ),
        heartbeat_seconds=current_app.config[
            "SELORA_WORKSPACE_HEARTBEAT_SECONDS"
        ],
    )


@web_bp.post("/draft/<draft_id>/send")
def send_import_draft_to_selora(
    draft_id: str,
) -> ResponseReturnValue:
    draft_repository = ImportDraftRepository()
    draft = draft_repository.get(draft_id=draft_id)

    if draft is None:
        abort(404)

    crawl_repository = CrawlSessionRepository()
    crawl_session = crawl_repository.get(session_id=draft.crawl_session_id)

    if crawl_session is None:
        abort(404)

    service = ImportDraftService(repository=draft_repository)
    service.ensure_product_data(draft=draft)

    draft = draft_repository.get(draft_id=draft_id)

    if draft is None:
        abort(404)

    validation = ImportDraftValidationService().validate(draft=draft)

    if not validation.can_send:
        return (
            render_template(
                "import_final_review.html",
                draft=draft,
                validation=validation,
                send_result=None,
                send_error=("قبل از ارسال، خطاهای مسدودکننده را اصلاح کنید."),
                send_request_id="",
                remote_error=None,
                remote_read_only=draft.is_remote_read_only,
                remote_read_only_reason=None,
                remote_retry_allowed=False,
                heartbeat_seconds=current_app.config[
                    "SELORA_WORKSPACE_HEARTBEAT_SECONDS"
                ],
            ),
            400,
        )

    try:
        coordinator = _remote_coordinator(
            repository=draft_repository,
        )
        coordinator.ensure_mutation_allowed(
            workspace=draft,
        )

        result = SeloraImportService(
            client=_selora_client(),
            mapper=SeloraPayloadMapper(),
        ).send(
            draft=draft,
            crawl_session=crawl_session,
            client_instance_id=(
                _client_instance_id()
            ),
        )

        coordinator.apply_import_result(
            workspace=draft,
            state=result.workspace,
        )

    except RemoteWorkspaceStateError as exc:
        return (
            render_template(
                "import_final_review.html",
                draft=draft,
                validation=validation,
                send_result=None,
                send_error=str(exc),
                send_request_id="",
                remote_error=str(exc),
                remote_read_only=True,
                remote_read_only_reason=str(exc),
                remote_retry_allowed=True,
                heartbeat_seconds=current_app.config[
                    "SELORA_WORKSPACE_HEARTBEAT_SECONDS"
                ],
            ),
            423,
        )

    except SeloraPayloadMappingError as exc:
        return (
            render_template(
                "import_final_review.html",
                draft=draft,
                validation=validation,
                send_result=None,
                send_error=str(exc),
                send_request_id="",
                remote_error=None,
                remote_read_only=draft.is_remote_read_only,
                remote_read_only_reason=None,
                remote_retry_allowed=False,
                heartbeat_seconds=current_app.config[
                    "SELORA_WORKSPACE_HEARTBEAT_SECONDS"
                ],
            ),
            422,
        )

    except SeloraApiError as exc:
        if not (
            isinstance(
                exc,
                SeloraApiResponseError,
            )
            and exc.status_code in {
                409,
                423,
            }
        ):
            logger.exception(
                "Failed to send import draft %s to Selora",
                draft_id,
            )

        request_id = (
            exc.request_id
            if isinstance(
                exc,
                SeloraApiResponseError,
            )
            else ""
        )
        message, reason, retry_allowed = (
            _remote_error_message(
                exc
            )
        )

        return (
            render_template(
                "import_final_review.html",
                draft=draft,
                validation=validation,
                send_result=None,
                send_error=message,
                send_request_id=request_id,
                remote_error=message,
                remote_read_only=True,
                remote_read_only_reason=reason,
                remote_retry_allowed=retry_allowed,
                heartbeat_seconds=current_app.config[
                    "SELORA_WORKSPACE_HEARTBEAT_SECONDS"
                ],
            ),
            (
                exc.status_code
                if isinstance(
                    exc,
                    SeloraApiResponseError,
                )
                and exc.status_code in {
                    409,
                    423,
                }
                else 502
            ),
        )

    return redirect(
        url_for(
            "web.import_draft_success",
            draft_id=draft.id,
            session_id=result.session_id,
            request_id=result.request_id,
            replayed=("1" if result.replayed else "0"),
            operation=result.operation,
            draft_count=result.draft_count,
        )
    )



@web_bp.post("/draft/<draft_id>/remote-lock/heartbeat")
def heartbeat_import_draft_lock(
    draft_id: str,
) -> ResponseReturnValue:
    repository = ImportDraftRepository()
    draft = repository.get(
        draft_id=draft_id
    )

    if draft is None:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "draft_not_found",
                    "message": "Workspace پیدا نشد.",
                }
            ),
            404,
        )

    try:
        state = _remote_coordinator(
            repository=repository,
        ).heartbeat(
            workspace=draft,
        )
    except RemoteWorkspaceStateError as exc:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "remote_workspace_read_only",
                    "message": str(exc),
                    "read_only_reason": str(exc),
                    "retry_allowed": True,
                }
            ),
            423,
        )
    except SeloraApiError as exc:
        return _remote_api_error_response(
            exc=exc
        )

    return jsonify(
        {
            "ok": True,
            "workflow_status": (
                state.workflow_status
            ),
            "is_editable": (
                state.is_editable
            ),
            "revision": (
                state.revision
            ),
            "lock_expires_at": (
                state.lock_expires_at.isoformat()
                if state.lock_expires_at
                is not None
                else None
            ),
        }
    )


@web_bp.post("/draft/<draft_id>/remote-lock/retry")
def retry_import_draft_lock(
    draft_id: str,
) -> ResponseReturnValue:
    repository = ImportDraftRepository()
    draft = repository.get(
        draft_id=draft_id
    )

    if draft is None:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "draft_not_found",
                    "message": "Workspace پیدا نشد.",
                }
            ),
            404,
        )

    crawl_repository = CrawlSessionRepository()
    crawl_session = crawl_repository.get(
        session_id=draft.crawl_session_id
    )

    if crawl_session is None:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "crawl_not_found",
                    "message": "منبع این Workspace پیدا نشد.",
                }
            ),
            404,
        )

    remote_state = _prepare_remote_editor_state(
        draft=draft,
        crawl_session=crawl_session,
        repository=repository,
    )

    refreshed_draft = (
        repository.get(
            draft_id=draft_id
        )
        or draft
    )

    if (
        remote_state.error is not None
        or remote_state.read_only_reason
        is not None
        or refreshed_draft.is_remote_read_only
    ):
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "remote_lock_unavailable",
                    "message": (
                        remote_state.error
                        or remote_state.read_only_reason
                        or "Workspace هنوز فقط‌خواندنی است."
                    ),
                    "read_only_reason": (
                        remote_state.read_only_reason
                    ),
                    "retry_allowed": (
                        remote_state.retry_allowed
                    ),
                }
            ),
            423,
        )

    return jsonify(
        {
            "ok": True,
            "message": "قفل ویرایش با موفقیت دریافت شد.",
            "revision": (
                refreshed_draft.remote_revision
            ),
            "lock_expires_at": (
                refreshed_draft.remote_lock_expires_at.isoformat()
                if refreshed_draft.remote_lock_expires_at
                is not None
                else None
            ),
        }
    )


@web_bp.post("/draft/<draft_id>/remote-lock/release")
def release_import_draft_lock(
    draft_id: str,
) -> ResponseReturnValue:
    repository = ImportDraftRepository()
    draft = repository.get(
        draft_id=draft_id
    )

    if draft is None:
        return (
            jsonify(
                {
                    "ok": False,
                }
            ),
            404,
        )

    try:
        _remote_coordinator(
            repository=repository,
        ).release(
            workspace=draft,
        )
    except SeloraApiError:
        logger.warning(
            (
                "Best-effort remote lock release "
                "failed for %s"
            ),
            draft_id,
            exc_info=True,
        )

    return jsonify(
        {
            "ok": True,
        }
    )


@web_bp.get("/draft/<draft_id>/success")
def import_draft_success(
    draft_id: str,
) -> ResponseReturnValue:
    repository = ImportDraftRepository()
    draft = repository.get(draft_id=draft_id)

    if draft is None:
        abort(404)

    session_id = request.args.get(
        "session_id",
        "",
    ).strip()

    request_id = request.args.get(
        "request_id",
        "",
    ).strip()

    replayed = (
        request.args.get(
            "replayed",
            "0",
        )
        == "1"
    )

    raw_operation = request.args.get(
        "operation"
    )
    operation: str | None = None

    if raw_operation is not None:
        normalized_operation = (
            raw_operation.strip()
        )

        if normalized_operation in {
            "created",
            "updated",
            "unchanged",
        }:
            operation = (
                normalized_operation
            )

    raw_draft_count = request.args.get(
        "draft_count",
        "0",
    ).strip()

    try:
        draft_count = max(
            int(raw_draft_count),
            0,
        )
    except ValueError:
        draft_count = 0

    template_context = {
        "draft": draft,
        "session_id": session_id,
        "request_id": request_id,
        "replayed": replayed,
        "draft_count": draft_count,
    }

    if operation is not None:
        template_context[
            "operation"
        ] = operation

    return render_template(
        "import_success.html",
        **template_context,
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
