from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from app.config import Config
from app.integrations.selora.client import SeloraApiClient, SeloraImportResult
from app.integrations.selora.payload_mapper import SeloraPayloadMapper, SeloraPayloadMappingError
from app.models import CrawlSession
from app.models.import_draft import ImportDraft
from app.services.media_storage_service import InstagramMediaStorageService


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

        for index, pending in enumerate(pending_uploads, start=1):
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
                request_id=f"{draft.id}:asset:{index}",
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
            if selected_asset.is_selected
        ]

        if not selected_assets:
            return ()

        storage_service = self.media_storage_service or InstagramMediaStorageService(
            root_path=Config.INSTAGRAM_MEDIA_STORAGE_DIR,
            timeout_seconds=Config.INSTAGRAM_MEDIA_STORAGE_TIMEOUT_SECONDS,
            max_bytes=Config.INSTAGRAM_MEDIA_STORAGE_MAX_BYTES,
        )

        if any(
            not self._stored_file_exists(storage_service=storage_service, asset=asset)
            for asset in selected_assets
        ):
            storage_service.persist_source(source=crawl_session)

        pending: list[PendingAssetUpload] = []

        for asset in selected_assets:
            file_path = storage_service.resolve_file_path(asset=asset)
            if file_path is None or not file_path.is_file() or file_path.stat().st_size <= 0:
                raise SeloraPayloadMappingError(
                    "فایل یکی از Assetهای انتخاب‌شده در ذخیره محلی موجود نیست و قابل ارسال به سلورا نیست."
                )

            sha256 = asset.local_sha256 or self._sha256(file_path)
            pending.append(
                PendingAssetUpload(
                    instagram_media_id=asset.media.media_id,
                    asset_type=asset.asset_type,
                    position=asset.position,
                    file_path=file_path,
                    content_type=asset.local_content_type,
                    sha256=sha256,
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
