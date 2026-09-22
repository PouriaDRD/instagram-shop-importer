from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path

from app.config import Config
from app.integrations.selora.client import (
    SeloraApiClient,
    SeloraApiError,
    SeloraApiNetworkError,
    SeloraApiResponseError,
    SeloraImportResult,
)
from app.integrations.selora.payload_mapper import SeloraPayloadMapper, SeloraPayloadMappingError
from app.models import CrawlSession
from app.models.import_draft import ImportDraft
from app.services.media_storage_service import InstagramMediaStorageService
from app.services.selora_media_derivative_service import (
    SeloraMediaDerivativeError,
    SeloraMediaDerivativeService,
)
from app.services.selora_upload_checkpoint_service import (
    SeloraUploadCheckpointService,
)

logger = logging.getLogger(__name__)




@dataclass(frozen=True, slots=True)
class PendingAssetUpload:
    instagram_media_id: str
    asset_type: str
    position: int
    file_path: Path
    content_type: str | None
    sha256: str


@dataclass(frozen=True, slots=True)
class SeloraImportService:
    client: SeloraApiClient
    mapper: SeloraPayloadMapper
    media_storage_service: InstagramMediaStorageService | None = None

    def send(
        self,
        *,
        draft: ImportDraft,
        crawl_session: CrawlSession,
        client_instance_id: str,
    ) -> SeloraImportResult:
        pending_uploads = self._prepare_selected_assets(
            draft=draft,
            crawl_session=crawl_session,
        )

        payload = self.mapper.build_import_payload(
            draft=draft,
            crawl_session=crawl_session,
            client_instance_id=client_instance_id,
        )
        result = self.client.send_import(
            payload=payload,
            request_id=draft.id,
        )

        if not pending_uploads:
            return result

        workspace_id = result.workspace.workspace_id
        lock_token = result.workspace.lock_token or draft.remote_lock_token

        if not workspace_id:
            raise SeloraPayloadMappingError(
                "سلورا شناسه Workspace را برای انتقال فایل‌ها برنگرداند."
            )
        if not lock_token:
            raise SeloraPayloadMappingError(
                "قفل Workspace برای انتقال فایل‌ها در دسترس نیست."
            )

        checkpoint_service = (
            SeloraUploadCheckpointService()
        )

        checkpoint = (
            checkpoint_service.load(
                draft_id=draft.id,
                workspace_id=workspace_id,
            )
        )

        total_uploads = len(
            pending_uploads
        )

        checkpoint_service.update_progress(
            draft_id=draft.id,
            workspace_id=workspace_id,
            checkpoint=checkpoint,
            status="running",
            total=total_uploads,
        )

        for index, pending in enumerate(
            pending_uploads,
            start=1,
        ):
            asset_key = (
                checkpoint_service.asset_key(
                    instagram_media_id=(
                        pending.instagram_media_id
                    ),
                    asset_type=pending.asset_type,
                    position=pending.position,
                )
            )

            if checkpoint_service.is_uploaded(
                checkpoint=checkpoint,
                asset_key=asset_key,
                sha256=pending.sha256,
            ):
                logger.info(
                    (
                        "Skipping already uploaded asset "
                        "%s/%s: media=%s type=%s "
                        "position=%s"
                    ),
                    index,
                    total_uploads,
                    pending.instagram_media_id,
                    pending.asset_type,
                    pending.position,
                )
                continue

            checkpoint_service.update_progress(
                draft_id=draft.id,
                workspace_id=workspace_id,
                checkpoint=checkpoint,
                status="running",
                total=total_uploads,
                current=index,
                current_media_id=(
                    pending.instagram_media_id
                ),
                current_asset_type=(
                    pending.asset_type
                ),
            )

            size_bytes = (
                pending.file_path.stat().st_size
            )

            request_id = (
                f"{draft.id}:asset:{index}"
            )

            logger.info(
                (
                    "Uploading asset %s/%s: "
                    "media=%s type=%s position=%s "
                    "size=%s bytes"
                ),
                index,
                total_uploads,
                pending.instagram_media_id,
                pending.asset_type,
                pending.position,
                size_bytes,
            )

            try:
                upload_result = (
                    self.client.upload_workspace_asset(
                        workspace_id=workspace_id,
                        client_workspace_id=draft.id,
                        client_instance_id=client_instance_id,
                        lock_token=lock_token,
                        expected_revision=result.workspace.revision,
                        instagram_media_id=pending.instagram_media_id,
                        asset_type=pending.asset_type,
                        position=pending.position,
                        sha256=pending.sha256,
                        file_path=pending.file_path,
                        content_type=pending.content_type,
                        request_id=request_id,
                    )
                )

            except SeloraApiError as exc:
                checkpoint_service.update_progress(
                    draft_id=draft.id,
                    workspace_id=workspace_id,
                    checkpoint=checkpoint,
                    status="failed",
                    total=total_uploads,
                    current=index,
                    current_media_id=(
                        pending.instagram_media_id
                    ),
                    current_asset_type=(
                        pending.asset_type
                    ),
                    error=str(exc),
                )

                logger.error(
                    (
                        "Asset upload failed %s/%s: "
                        "media=%s type=%s position=%s "
                        "status=%s code=%s "
                        "request_id=%s retryable=%s "
                        "content_type=%s response=%s"
                    ),
                    index,
                    total_uploads,
                    pending.instagram_media_id,
                    pending.asset_type,
                    pending.position,
                    getattr(
                        exc,
                        "status_code",
                        "",
                    ),
                    getattr(
                        exc,
                        "code",
                        exc.__class__.__name__,
                    ),
                    getattr(
                        exc,
                        "request_id",
                        request_id,
                    ),
                    getattr(
                        exc,
                        "retryable",
                        False,
                    ),
                    getattr(
                        exc,
                        "content_type",
                        "",
                    ),
                    getattr(
                        exc,
                        "response_preview",
                        "",
                    ),
                )

                raise

            checkpoint_service.mark_uploaded(
                draft_id=draft.id,
                workspace_id=workspace_id,
                checkpoint=checkpoint,
                asset_key=asset_key,
                sha256=pending.sha256,
                request_id=(
                    upload_result.request_id
                ),
            )

            logger.info(
                (
                    "Asset uploaded successfully "
                    "%s/%s: media=%s type=%s "
                    "position=%s operation=%s"
                ),
                index,
                total_uploads,
                pending.instagram_media_id,
                pending.asset_type,
                pending.position,
                upload_result.operation,
            )

        checkpoint_service.update_progress(
            draft_id=draft.id,
            workspace_id=workspace_id,
            checkpoint=checkpoint,
            status="complete",
            total=total_uploads,
            current=total_uploads,
        )

        return result

    def _prepare_selected_assets(
        self,
        *,
        draft: ImportDraft,
        crawl_session: CrawlSession,
    ) -> tuple[PendingAssetUpload, ...]:
        selected_assets = [
            selected_asset.asset
            for item in draft.items
            if item.is_selected
            for selected_asset in item.selected_assets
            if (
                selected_asset.is_selected
                and selected_asset.asset.asset_type != "video"
            )
        ]

        logger.info(
            (
                "Preparing selected Selora assets: "
                "draft=%s selected_assets=%s "
                "storage_root=%s"
            ),
            draft.id,
            len(selected_assets),
            Config.INSTAGRAM_MEDIA_STORAGE_DIR,
        )

        if not selected_assets:
            logger.info(
                "No selected assets require Selora upload: draft=%s",
                draft.id,
            )
            return ()

        storage_service = self.media_storage_service or InstagramMediaStorageService(
            root_path=Config.INSTAGRAM_MEDIA_STORAGE_DIR,
            timeout_seconds=Config.INSTAGRAM_MEDIA_STORAGE_TIMEOUT_SECONDS,
            max_bytes=Config.INSTAGRAM_MEDIA_STORAGE_MAX_BYTES,
        )

        missing_assets = [
            asset
            for asset in selected_assets
            if not self._stored_file_exists(
                storage_service=storage_service,
                asset=asset,
            )
        ]

        if missing_assets:
            storage_service.persist_source(
                source=crawl_session,
                assets=missing_assets,
            )

        pending: list[PendingAssetUpload] = []
        derivative_service = (
            SeloraMediaDerivativeService()
        )

        for asset in selected_assets:
            file_path = storage_service.resolve_file_path(asset=asset)
            if file_path is None or not file_path.is_file() or file_path.stat().st_size <= 0:
                raise SeloraPayloadMappingError(
                    "فایل یکی از Assetهای انتخاب‌شده در ذخیره محلی موجود نیست و قابل ارسال به سلورا نیست."
                )

            logger.info(
                (
                    "Preparing Selora asset: "
                    "draft=%s media_id=%s "
                    "type=%s position=%s "
                    "file=%s bytes=%s"
                ),
                draft.id,
                asset.media.media_id,
                asset.asset_type,
                asset.position,
                file_path,
                file_path.stat().st_size,
            )

            source_sha256 = (
                asset.local_sha256
                or self._sha256(file_path)
            )

            try:
                prepared = (
                    derivative_service.prepare_webp(
                        source_path=file_path,
                        source_sha256=source_sha256,
                    )
                )
            except SeloraMediaDerivativeError as exc:
                raise SeloraPayloadMappingError(
                    (
                        "Preparing selected Instagram "
                        "image for Selora failed."
                    )
                ) from exc

            logger.info(
                (
                    "Selora derivative ready: "
                    "draft=%s media_id=%s "
                    "type=%s position=%s "
                    "file=%s bytes=%s sha256=%s"
                ),
                draft.id,
                asset.media.media_id,
                asset.asset_type,
                asset.position,
                prepared.file_path,
                prepared.file_path.stat().st_size,
                prepared.sha256,
            )

            pending.append(
                PendingAssetUpload(
                    instagram_media_id=asset.media.media_id,
                    asset_type=asset.asset_type,
                    position=asset.position,
                    file_path=prepared.file_path,
                    content_type=prepared.content_type,
                    sha256=prepared.sha256,
                )
            )

        return tuple(pending)

    @staticmethod
    def _stored_file_exists(*, storage_service: InstagramMediaStorageService, asset) -> bool:
        path = storage_service.resolve_file_path(asset=asset)
        return path is not None and path.is_file() and path.stat().st_size > 0

    @staticmethod
    def _sha256(file_path: Path) -> str:
        digest = hashlib.sha256()
        with file_path.open("rb") as file_handle:
            while True:
                chunk = file_handle.read(64 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()
