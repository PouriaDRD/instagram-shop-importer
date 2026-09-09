from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

import requests


class SeloraApiError(RuntimeError):
    """Base exception for Selora API integration failures."""


class SeloraApiConfigurationError(SeloraApiError):
    """Selora API configuration is incomplete."""


class SeloraApiNetworkError(SeloraApiError):
    """Selora could not be reached or timed out."""


class SeloraApiResponseError(SeloraApiError):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        request_id: str,
    ) -> None:
        super().__init__(
            message
        )
        self.status_code = status_code
        self.code = code
        self.request_id = request_id


@dataclass(frozen=True, slots=True)
class SeloraWorkspaceState:
    workspace_id: str
    workflow_status: str
    is_editable: bool
    revision: int
    lock_token: str | None
    lock_expires_at: datetime | None
    request_id: str


@dataclass(frozen=True, slots=True)
class SeloraImportResult:
    session_id: str
    replayed: bool
    operation: str
    media_count: int
    draft_count: int
    workspace: SeloraWorkspaceState
    request_id: str


@dataclass(frozen=True, slots=True)
class SeloraAssetUploadResult:
    asset_id: str
    operation: str
    file_name: str
    sha256: str
    size_bytes: int
    request_id: str


class SeloraApiClient:
    IMPORT_PATH = "/instagram-importer/api/v1/imports/"
    WORKSPACE_RESOLVE_PATH = (
        "/instagram-importer/api/v1/imports/workspaces/resolve/"
    )

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        connect_timeout_seconds: int = 5,
        read_timeout_seconds: int = 30,
        http_session: requests.Session | None = None,
    ) -> None:
        normalized_base_url = (
            base_url.strip().rstrip("/")
        )
        normalized_api_key = (
            api_key.strip()
        )

        if not normalized_base_url:
            raise SeloraApiConfigurationError(
                "SELORA_API_BASE_URL تنظیم نشده است."
            )

        if not normalized_api_key:
            raise SeloraApiConfigurationError(
                "SELORA_API_KEY تنظیم نشده است."
            )

        self._base_url = (
            normalized_base_url
        )
        self._api_key = (
            normalized_api_key
        )
        self._timeout = (
            connect_timeout_seconds,
            read_timeout_seconds,
        )
        self._http = (
            http_session
            or requests.Session()
        )

    def resolve_workspace(
        self,
        *,
        instagram_username: str,
        client_workspace_id: str,
        client_instance_id: str,
        request_id: str | None = None,
    ) -> SeloraWorkspaceState:
        body, response_request_id = self._request_json(
            method="POST",
            path=self.WORKSPACE_RESOLVE_PATH,
            json_payload={
                "instagram_username": instagram_username,
                "client_workspace_id": client_workspace_id,
                "client_instance_id": client_instance_id,
            },
            request_id=request_id,
        )

        return self._parse_workspace(
            body=body,
            request_id=response_request_id,
        )

    def get_workspace(
        self,
        *,
        workspace_id: str,
        client_instance_id: str,
        request_id: str | None = None,
    ) -> SeloraWorkspaceState:
        path = (
            "/instagram-importer/api/v1/imports/"
            f"workspaces/{workspace_id}/"
        )

        body, response_request_id = self._request_json(
            method="GET",
            path=path,
            query_params={
                "client_instance_id": client_instance_id,
            },
            request_id=request_id,
        )

        return self._parse_workspace(
            body=body,
            request_id=response_request_id,
        )

    def acquire_workspace_lock(
        self,
        *,
        workspace_id: str,
        client_workspace_id: str,
        client_instance_id: str,
        expected_revision: int | None,
        request_id: str | None = None,
    ) -> SeloraWorkspaceState:
        return self._workspace_lock_action(
            workspace_id=workspace_id,
            suffix="lock/",
            payload={
                "client_workspace_id": client_workspace_id,
                "client_instance_id": client_instance_id,
                "expected_revision": expected_revision,
            },
            request_id=request_id,
        )

    def renew_workspace_lock(
        self,
        *,
        workspace_id: str,
        client_workspace_id: str,
        client_instance_id: str,
        lock_token: str,
        request_id: str | None = None,
    ) -> SeloraWorkspaceState:
        return self._workspace_lock_action(
            workspace_id=workspace_id,
            suffix="lock/renew/",
            payload={
                "client_workspace_id": client_workspace_id,
                "client_instance_id": client_instance_id,
                "lock_token": lock_token,
            },
            request_id=request_id,
        )

    def release_workspace_lock(
        self,
        *,
        workspace_id: str,
        client_workspace_id: str,
        client_instance_id: str,
        lock_token: str,
        request_id: str | None = None,
    ) -> SeloraWorkspaceState:
        body, response_request_id = self._request_json(
            method="POST",
            path=(
                "/instagram-importer/api/v1/imports/"
                f"workspaces/{workspace_id}/lock/release/"
            ),
            json_payload={
                "client_workspace_id": client_workspace_id,
                "client_instance_id": client_instance_id,
                "lock_token": lock_token,
            },
            request_id=request_id,
        )

        workspace = body.get(
            "workspace"
        )

        if not isinstance(
            workspace,
            dict,
        ):
            raise self._invalid_success(
                request_id=response_request_id,
            )

        revision = self._required_int(
            workspace,
            "revision",
            request_id=response_request_id,
        )

        return SeloraWorkspaceState(
            workspace_id=workspace_id,
            workflow_status="unknown",
            is_editable=False,
            revision=revision,
            lock_token=None,
            lock_expires_at=None,
            request_id=response_request_id,
        )

    def send_import(
        self,
        *,
        payload: Mapping[str, Any],
        request_id: str | None = None,
    ) -> SeloraImportResult:
        body, response_request_id = self._request_json(
            method="POST",
            path=self.IMPORT_PATH,
            json_payload=dict(
                payload
            ),
            request_id=request_id,
        )

        session = body.get(
            "session"
        )

        if not isinstance(
            session,
            dict,
        ):
            raise self._invalid_success(
                request_id=response_request_id,
            )

        operation = body.get(
            "operation",
            (
                "unchanged"
                if session.get("replayed")
                else "created"
            ),
        )

        if (
            not isinstance(
                operation,
                str,
            )
            or operation
            not in {
                "created",
                "updated",
                "unchanged",
            }
        ):
            raise self._invalid_success(
                request_id=response_request_id,
            )

        session_id = self._required_str(
            session,
            "id",
            request_id=response_request_id,
        )

        replayed = session.get(
            "replayed"
        )

        if not isinstance(
            replayed,
            bool,
        ):
            raise self._invalid_success(
                request_id=response_request_id,
            )

        media_count = self._required_int(
            session,
            "media_count",
            request_id=response_request_id,
        )
        draft_count = self._required_int(
            session,
            "draft_count",
            request_id=response_request_id,
        )

        raw_workspace = body.get(
            "workspace"
        )

        if isinstance(
            raw_workspace,
            dict,
        ):
            workspace = self._parse_workspace(
                body=body,
                request_id=response_request_id,
            )
        elif (
            "operation" not in body
            and "workspace" not in body
        ):
            # Compatibility with the pre-Phase-4D success contract.
            # Production Phase 4D responses include both operation and
            # workspace, but older unit/integration seams may still return
            # only the legacy session envelope.
            workspace = SeloraWorkspaceState(
                workspace_id="",
                workflow_status="unknown",
                is_editable=False,
                revision=0,
                lock_token=None,
                lock_expires_at=None,
                request_id=response_request_id,
            )
        else:
            raise self._invalid_success(
                request_id=response_request_id,
            )

        return SeloraImportResult(
            session_id=session_id,
            replayed=replayed,
            operation=operation,
            media_count=media_count,
            draft_count=draft_count,
            workspace=workspace,
            request_id=response_request_id,
        )

    def upload_workspace_asset(
        self,
        *,
        workspace_id: str,
        client_workspace_id: str,
        client_instance_id: str,
        lock_token: str,
        expected_revision: int,
        instagram_media_id: str,
        asset_type: str,
        position: int,
        sha256: str,
        file_path: Path,
        content_type: str | None,
        request_id: str | None = None,
    ) -> SeloraAssetUploadResult:
        if not file_path.is_file():
            raise SeloraApiError(
                f"فایل cache محلی برای ارسال پیدا نشد: {file_path}"
            )

        effective_request_id = (
            request_id.strip()
            if request_id is not None and request_id.strip()
            else str(uuid4())
        )
        path = (
            "/instagram-importer/api/v1/imports/"
            f"workspaces/{workspace_id}/assets/upload/"
        )
        data = {
            "client_workspace_id": client_workspace_id,
            "client_instance_id": client_instance_id,
            "lock_token": lock_token,
            "expected_revision": str(expected_revision),
            "instagram_media_id": instagram_media_id,
            "asset_type": asset_type,
            "position": str(position),
            "sha256": sha256,
        }
        headers = {
            "X-API-Key": self._api_key,
            "X-Request-ID": effective_request_id,
            "Accept": "application/json",
        }

        try:
            with file_path.open("rb") as file_handle:
                response = self._http.post(
                    f"{self._base_url}{path}",
                    data=data,
                    files={
                        "file": (
                            file_path.name,
                            file_handle,
                            content_type or "application/octet-stream",
                        )
                    },
                    headers=headers,
                    timeout=self._timeout,
                )
        except requests.RequestException as exc:
            raise SeloraApiNetworkError(
                "ارسال فایل به API سلورا با خطای شبکه مواجه شد."
            ) from exc

        response_request_id = (
            response.headers.get("X-Request-ID", "").strip()
            or effective_request_id
        )
        body = self._read_json_object(response=response)

        if response.status_code not in {200, 201}:
            error = body.get("error")
            code = "selora_api_error"
            message = "ارسال فایل به سلورا ناموفق بود."
            if isinstance(error, dict):
                raw_code = error.get("code")
                raw_message = error.get("message")
                if isinstance(raw_code, str) and raw_code.strip():
                    code = raw_code.strip()
                if isinstance(raw_message, str) and raw_message.strip():
                    message = raw_message.strip()
            raise SeloraApiResponseError(
                status_code=response.status_code,
                code=code,
                message=message,
                request_id=response_request_id,
            )

        operation = body.get("operation")
        if not isinstance(operation, str) or operation not in {
            "uploaded", "updated", "unchanged"
        }:
            raise self._invalid_success(request_id=response_request_id)

        asset = body.get("asset")
        if not isinstance(asset, dict):
            raise self._invalid_success(request_id=response_request_id)

        return SeloraAssetUploadResult(
            asset_id=self._required_str(asset, "id", request_id=response_request_id),
            operation=operation,
            file_name=self._required_str(asset, "file_name", request_id=response_request_id),
            sha256=self._required_str(asset, "sha256", request_id=response_request_id),
            size_bytes=self._required_int(asset, "size_bytes", request_id=response_request_id),
            request_id=response_request_id,
        )

    def _workspace_lock_action(
        self,
        *,
        workspace_id: str,
        suffix: str,
        payload: Mapping[str, Any],
        request_id: str | None,
    ) -> SeloraWorkspaceState:
        body, response_request_id = self._request_json(
            method="POST",
            path=(
                "/instagram-importer/api/v1/imports/"
                f"workspaces/{workspace_id}/{suffix}"
            ),
            json_payload=dict(
                payload
            ),
            request_id=request_id,
        )

        return self._parse_workspace(
            body=body,
            request_id=response_request_id,
        )

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        json_payload: Mapping[str, Any] | None = None,
        query_params: Mapping[str, Any] | None = None,
        request_id: str | None = None,
    ) -> tuple[
        dict[str, Any],
        str,
    ]:
        effective_request_id = (
            request_id.strip()
            if (
                request_id is not None
                and request_id.strip()
            )
            else str(
                uuid4()
            )
        )

        request_kwargs: dict[str, Any] = {
            "headers": {
                "X-API-Key": self._api_key,
                "X-Request-ID": effective_request_id,
                "Accept": "application/json",
            },
            "timeout": self._timeout,
        }

        if json_payload is not None:
            request_kwargs["json"] = dict(
                json_payload
            )

        if query_params is not None:
            request_kwargs["params"] = dict(
                query_params
            )

        url = f"{self._base_url}{path}"

        try:
            normalized_method = method.upper()

            if normalized_method == "POST":
                response = self._http.post(
                    url,
                    **request_kwargs,
                )
            elif normalized_method == "GET":
                response = self._http.get(
                    url,
                    **request_kwargs,
                )
            else:
                response = self._http.request(
                    method=normalized_method,
                    url=url,
                    **request_kwargs,
                )
        except requests.RequestException as exc:
            raise SeloraApiNetworkError(
                "ارتباط با API سلورا برقرار نشد."
            ) from exc

        response_request_id = (
            response.headers.get(
                "X-Request-ID",
                "",
            ).strip()
            or effective_request_id
        )

        body = self._read_json_object(
            response=response
        )

        if response.status_code not in {
            200,
            201,
        }:
            error = body.get(
                "error"
            )
            code = "selora_api_error"
            message = (
                "درخواست API سلورا ناموفق بود."
            )

            if isinstance(
                error,
                dict,
            ):
                raw_code = error.get(
                    "code"
                )
                raw_message = error.get(
                    "message"
                )

                if (
                    isinstance(
                        raw_code,
                        str,
                    )
                    and raw_code.strip()
                ):
                    code = raw_code.strip()

                if (
                    isinstance(
                        raw_message,
                        str,
                    )
                    and raw_message.strip()
                ):
                    message = raw_message.strip()

            raise SeloraApiResponseError(
                status_code=response.status_code,
                code=code,
                message=message,
                request_id=response_request_id,
            )

        return (
            body,
            response_request_id,
        )

    def _parse_workspace(
        self,
        *,
        body: Mapping[str, Any],
        request_id: str,
    ) -> SeloraWorkspaceState:
        workspace = body.get(
            "workspace"
        )

        if not isinstance(
            workspace,
            dict,
        ):
            raise self._invalid_success(
                request_id=request_id,
            )

        workspace_id = self._required_str(
            workspace,
            "id",
            request_id=request_id,
        )
        workflow_status = self._required_str(
            workspace,
            "workflow_status",
            request_id=request_id,
        )
        is_editable = workspace.get(
            "is_editable"
        )

        if not isinstance(
            is_editable,
            bool,
        ):
            raise self._invalid_success(
                request_id=request_id,
            )

        revision = self._required_int(
            workspace,
            "revision",
            request_id=request_id,
        )

        lock = workspace.get(
            "lock"
        )
        lock_token: str | None = None
        lock_expires_at: datetime | None = None

        if isinstance(
            lock,
            dict,
        ):
            raw_token = lock.get(
                "token"
            )

            if (
                isinstance(
                    raw_token,
                    str,
                )
                and raw_token.strip()
            ):
                lock_token = raw_token.strip()

            raw_expires_at = lock.get(
                "expires_at"
            )

            if (
                isinstance(
                    raw_expires_at,
                    str,
                )
                and raw_expires_at.strip()
            ):
                try:
                    lock_expires_at = (
                        datetime.fromisoformat(
                            raw_expires_at
                        )
                    )
                except ValueError as exc:
                    raise self._invalid_success(
                        request_id=request_id,
                    ) from exc

        return SeloraWorkspaceState(
            workspace_id=workspace_id,
            workflow_status=workflow_status,
            is_editable=is_editable,
            revision=revision,
            lock_token=lock_token,
            lock_expires_at=lock_expires_at,
            request_id=request_id,
        )

    @staticmethod
    def _required_str(
        mapping: Mapping[str, Any],
        key: str,
        *,
        request_id: str,
    ) -> str:
        value = mapping.get(
            key
        )

        if (
            not isinstance(
                value,
                str,
            )
            or not value.strip()
        ):
            raise SeloraApiResponseError(
                status_code=200,
                code="invalid_success_response",
                message="پاسخ موفق سلورا ساختار معتبر ندارد.",
                request_id=request_id,
            )

        return value.strip()

    @staticmethod
    def _required_int(
        mapping: Mapping[str, Any],
        key: str,
        *,
        request_id: str,
    ) -> int:
        value = mapping.get(
            key
        )

        if (
            isinstance(
                value,
                bool,
            )
            or not isinstance(
                value,
                int,
            )
        ):
            raise SeloraApiResponseError(
                status_code=200,
                code="invalid_success_response",
                message="پاسخ موفق سلورا ساختار معتبر ندارد.",
                request_id=request_id,
            )

        return value

    @staticmethod
    def _invalid_success(
        *,
        request_id: str,
    ) -> SeloraApiResponseError:
        return SeloraApiResponseError(
            status_code=200,
            code="invalid_success_response",
            message="پاسخ موفق سلورا ساختار معتبر ندارد.",
            request_id=request_id,
        )

    @staticmethod
    def _read_json_object(
        *,
        response: requests.Response,
    ) -> dict[str, Any]:
        try:
            body: object = response.json()
        except ValueError as exc:
            raise SeloraApiResponseError(
                status_code=response.status_code,
                code="invalid_json_response",
                message="سلورا پاسخ JSON معتبر برنگرداند.",
                request_id=response.headers.get(
                    "X-Request-ID",
                    "",
                ).strip(),
            ) from exc

        if not isinstance(
            body,
            dict,
        ):
            raise SeloraApiResponseError(
                status_code=response.status_code,
                code="invalid_json_response",
                message="پاسخ JSON سلورا باید object باشد.",
                request_id=response.headers.get(
                    "X-Request-ID",
                    "",
                ).strip(),
            )

        return body
