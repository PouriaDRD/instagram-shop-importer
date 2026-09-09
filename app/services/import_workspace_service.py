from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from app.models import InstagramSource
from app.models.import_workspace import (
    ImportProductData,
    ImportWorkspace,
    ImportWorkspaceItem,
    LocalSyncStatus,
)
from app.models.media import InstagramAsset
from app.repositories.import_workspace_repository import (
    ImportWorkspaceRepository,
)

logger = logging.getLogger("app")


@dataclass(frozen=True, slots=True)
class ImportWorkspaceItemUpdate:
    item_id: str
    is_selected: bool
    product_name: str
    description: str
    sale_price: int | None
    list_price: int | None
    stock: int
    colors: tuple[str, ...]
    sizes: tuple[str, ...]
    primary_asset_id: str | None


class ImportWorkspaceService:
    def __init__(
        self,
        *,
        repository: ImportWorkspaceRepository,
    ) -> None:
        self._repository = repository

    def create_or_update_from_source(
        self,
        *,
        source: InstagramSource,
        selected_media_ids: set[str],
        selected_asset_ids: set[str],
    ) -> ImportWorkspace:
        self._validate_selection(
            source=source,
            selected_media_ids=selected_media_ids,
            selected_asset_ids=selected_asset_ids,
        )

        workspace = (
            self._repository.get_current_for_session(
                crawl_session_id=source.id,
            )
        )

        is_new = workspace is None

        if workspace is None:
            workspace = self._repository.create(
                crawl_session_id=source.id,
            )

        self._ensure_editable(
            workspace=workspace,
        )

        try:
            self._sync_workspace_selection(
                workspace=workspace,
                source=source,
                selected_media_ids=selected_media_ids,
                selected_asset_ids=selected_asset_ids,
            )

            self._mark_pending(
                workspace=workspace,
            )

            workspace.updated_at = datetime.now(
                timezone.utc
            )

            self._repository.commit()

        except Exception:
            self._repository.rollback()

            logger.exception(
                (
                    "Failed to synchronize import "
                    "workspace for Instagram source %s"
                ),
                source.id,
            )

            raise

        logger.info(
            (
                "Import workspace %s %s for source %s "
                "with %s selected media"
            ),
            workspace.id,
            (
                "created"
                if is_new
                else "updated"
            ),
            source.id,
            len(selected_media_ids),
        )

        return workspace

    def create_or_update_from_session(
        self,
        *,
        crawl_session: InstagramSource,
        selected_media_ids: set[str],
        selected_asset_ids: set[str],
    ) -> ImportWorkspace:
        return self.create_or_update_from_source(
            source=crawl_session,
            selected_media_ids=selected_media_ids,
            selected_asset_ids=selected_asset_ids,
        )

    def create_from_session(
        self,
        *,
        crawl_session: InstagramSource,
        selected_media_ids: set[str],
        selected_asset_ids: set[str],
    ) -> ImportWorkspace:
        return self.create_or_update_from_source(
            source=crawl_session,
            selected_media_ids=selected_media_ids,
            selected_asset_ids=selected_asset_ids,
        )

    def ensure_product_data(
        self,
        *,
        workspace: ImportWorkspace | None = None,
        draft: ImportWorkspace | None = None,
    ) -> None:
        target = workspace or draft

        if target is None:
            raise ValueError(
                "Import workspace is required."
            )

        self._ensure_editable(
            workspace=target,
        )

        created = False

        try:
            for item in target.items:
                if not item.is_selected:
                    continue

                if item.product_data is None:
                    self._repository.add_product_data(
                        item=item,
                        description=(
                            item.media.caption or ""
                        ).strip(),
                    )
                    created = True

            if created:
                self._mark_pending(
                    workspace=target,
                )
                target.updated_at = datetime.now(
                    timezone.utc
                )
                self._repository.commit()

        except Exception:
            self._repository.rollback()
            logger.exception(
                (
                    "Failed to prepare product data "
                    "for workspace %s"
                ),
                target.id,
            )
            raise

    def update_workspace(
        self,
        *,
        workspace: ImportWorkspace,
        updates: list[
            ImportWorkspaceItemUpdate
        ],
    ) -> None:
        self._ensure_editable(
            workspace=workspace,
        )

        items_by_id = {
            item.id: item
            for item in workspace.items
        }

        update_ids = {
            update.item_id
            for update in updates
        }

        unknown_ids = (
            update_ids - items_by_id.keys()
        )

        if unknown_ids:
            raise ValueError(
                (
                    "One or more workspace items "
                    "do not belong to this workspace."
                )
            )

        try:
            for update in updates:
                item = items_by_id[
                    update.item_id
                ]

                product_data = item.product_data

                if product_data is None:
                    product_data = (
                        self._repository.add_product_data(
                            item=item,
                            description=(
                                item.media.caption
                                or ""
                            ).strip(),
                        )
                    )

                self._validate_update(
                    update
                )

                self._apply_update(
                    item=item,
                    product_data=product_data,
                    update=update,
                )

            self._mark_pending(
                workspace=workspace,
            )

            workspace.updated_at = datetime.now(
                timezone.utc
            )

            self._repository.commit()

        except Exception:
            self._repository.rollback()

            logger.exception(
                (
                    "Failed to update import "
                    "workspace %s"
                ),
                workspace.id,
            )

            raise

    def update_draft(
        self,
        *,
        draft: ImportWorkspace,
        updates: list[
            ImportWorkspaceItemUpdate
        ],
    ) -> None:
        self.update_workspace(
            workspace=draft,
            updates=updates,
        )

    def mark_syncing(
        self,
        *,
        workspace: ImportWorkspace,
    ) -> None:
        self._ensure_editable(
            workspace=workspace,
        )

        try:
            workspace.local_sync_status = (
                LocalSyncStatus.SYNCING.value
            )
            workspace.last_sync_error = None
            workspace.updated_at = datetime.now(
                timezone.utc
            )
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise

    def mark_synced(
        self,
        *,
        workspace: ImportWorkspace,
    ) -> None:
        """
        Record a successful outbound synchronization.

        This does NOT close or replace the workspace.
        """

        self._ensure_editable(
            workspace=workspace,
        )

        try:
            now = datetime.now(
                timezone.utc
            )

            workspace.local_sync_status = (
                LocalSyncStatus.SYNCED.value
            )
            workspace.last_synced_at = now
            workspace.last_sync_error = None
            workspace.updated_at = now

            # Legacy `status` intentionally remains unchanged.
            self._repository.commit()

        except Exception:
            self._repository.rollback()

            logger.exception(
                (
                    "Failed to mark import "
                    "workspace %s as synced"
                ),
                workspace.id,
            )

            raise

    def mark_sync_error(
        self,
        *,
        workspace: ImportWorkspace,
        error_message: str,
    ) -> None:
        try:
            workspace.local_sync_status = (
                LocalSyncStatus.ERROR.value
            )
            workspace.last_sync_error = (
                error_message.strip()[:2000]
            )
            workspace.updated_at = datetime.now(
                timezone.utc
            )
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise

    def mark_sent(
        self,
        *,
        draft: ImportWorkspace,
    ) -> None:
        """
        Legacy route compatibility.

        Old code calls mark_sent(). It now means "mark this permanent
        workspace synchronized" and no longer changes draft.status to sent.
        """

        self.mark_synced(
            workspace=draft,
        )

    @staticmethod
    def _mark_pending(
        *,
        workspace: ImportWorkspace,
    ) -> None:
        workspace.local_sync_status = (
            LocalSyncStatus.PENDING.value
        )
        workspace.last_sync_error = None

    @staticmethod
    def _ensure_editable(
        *,
        workspace: ImportWorkspace,
    ) -> None:
        if workspace.is_remote_read_only:
            raise ValueError(
                (
                    "این فضای واردسازی در سلورا "
                    "نهایی یا قفل شده و فقط قابل مشاهده است."
                )
            )

    def _validate_selection(
        self,
        *,
        source: InstagramSource,
        selected_media_ids: set[str],
        selected_asset_ids: set[str],
    ) -> None:
        if source.status != "completed":
            raise ValueError(
                (
                    "Only successfully synchronized "
                    "Instagram sources can update "
                    "the import workspace."
                )
            )

        if not selected_media_ids:
            raise ValueError(
                (
                    "At least one media item "
                    "must be selected."
                )
            )

        available_media = {
            media.id: media
            for media in source.media
        }

        unknown_media_ids = (
            selected_media_ids
            - available_media.keys()
        )

        if unknown_media_ids:
            raise ValueError(
                (
                    "One or more selected media items "
                    "do not belong to this Instagram source."
                )
            )

        selected_media_asset_ids = {
            asset.id
            for media in source.media
            if media.id
            in selected_media_ids
            for asset in media.assets
        }

        unknown_asset_ids = (
            selected_asset_ids
            - selected_media_asset_ids
        )

        if unknown_asset_ids:
            raise ValueError(
                (
                    "One or more selected assets "
                    "do not belong to selected media."
                )
            )

    def _sync_workspace_selection(
        self,
        *,
        workspace: ImportWorkspace,
        source: InstagramSource,
        selected_media_ids: set[str],
        selected_asset_ids: set[str],
    ) -> None:
        existing_items = {
            item.instagram_media_id: item
            for item in workspace.items
        }

        selected_media = [
            media
            for media in source.media
            if media.id
            in selected_media_ids
        ]

        for item in workspace.items:
            item.is_selected = (
                item.instagram_media_id
                in selected_media_ids
            )

        for item_position, media in enumerate(
            selected_media
        ):
            item = existing_items.get(
                media.id
            )

            if item is None:
                item = (
                    self._repository.add_item(
                        draft=workspace,
                        crawled_media_id=media.id,
                        position=item_position,
                    )
                )

                self._repository.add_product_data(
                    item=item,
                    description=(
                        media.caption or ""
                    ).strip(),
                )

                existing_items[
                    media.id
                ] = item

            item.position = item_position
            item.is_selected = True

            self._sync_item_assets(
                item=item,
                media_assets=media.assets,
                selected_asset_ids=selected_asset_ids,
            )

    def _sync_item_assets(
        self,
        *,
        item: ImportWorkspaceItem,
        media_assets: list[
            InstagramAsset
        ],
        selected_asset_ids: set[str],
    ) -> None:
        existing_assets = {
            selection.instagram_asset_id:
                selection
            for selection
            in item.selected_assets
        }

        desired_assets = [
            asset
            for asset in media_assets
            if asset.id
            in selected_asset_ids
        ]

        desired_ids = {
            asset.id
            for asset in desired_assets
        }

        current_primary_id = next(
            (
                selection.instagram_asset_id
                for selection
                in item.selected_assets
                if (
                    selection.is_selected
                    and selection.is_primary
                    and (
                        selection.instagram_asset_id
                        in desired_ids
                    )
                )
            ),
            None,
        )

        primary_id = (
            current_primary_id
            or (
                desired_assets[0].id
                if desired_assets
                else None
            )
        )

        for selection in item.selected_assets:
            selection.is_selected = (
                selection.instagram_asset_id
                in desired_ids
            )

            if not selection.is_selected:
                selection.is_primary = False

        for asset_position, asset in enumerate(
            desired_assets
        ):
            selection = existing_assets.get(
                asset.id
            )

            if selection is None:
                selection = (
                    self._repository.add_asset(
                        item=item,
                        crawled_asset_id=asset.id,
                        position=asset_position,
                        is_primary=(
                            asset.id
                            == primary_id
                        ),
                    )
                )

                existing_assets[
                    asset.id
                ] = selection

            selection.position = asset_position
            selection.is_selected = True
            selection.is_primary = (
                asset.id == primary_id
            )

    @staticmethod
    def _validate_update(
        update: ImportWorkspaceItemUpdate,
    ) -> None:
        if len(update.product_name) > 255:
            raise ValueError(
                (
                    "نام محصول نمی‌تواند بیشتر "
                    "از ۲۵۵ کاراکتر باشد."
                )
            )

        if (
            update.sale_price is not None
            and update.sale_price < 0
        ):
            raise ValueError(
                "قیمت فروش نمی‌تواند منفی باشد."
            )

        if (
            update.list_price is not None
            and update.list_price < 0
        ):
            raise ValueError(
                (
                    "قیمت قبل از تخفیف "
                    "نمی‌تواند منفی باشد."
                )
            )

        if (
            update.sale_price is not None
            and update.list_price is not None
            and (
                update.sale_price
                > update.list_price
            )
        ):
            raise ValueError(
                (
                    "قیمت فروش نمی‌تواند از قیمت "
                    "قبل از تخفیف بیشتر باشد."
                )
            )

        if update.stock < 0:
            raise ValueError(
                "موجودی نمی‌تواند منفی باشد."
            )

    @staticmethod
    def _apply_update(
        *,
        item: ImportWorkspaceItem,
        product_data: ImportProductData,
        update: ImportWorkspaceItemUpdate,
    ) -> None:
        item.is_selected = update.is_selected
        product_data.product_name = (
            update.product_name.strip()
        )
        product_data.description = (
            update.description.strip()
        )
        product_data.sale_price = (
            update.sale_price
        )
        product_data.list_price = (
            update.list_price
        )
        product_data.stock = update.stock
        product_data.colors = list(
            ImportWorkspaceService
            ._normalize_values(
                update.colors
            )
        )
        product_data.sizes = list(
            ImportWorkspaceService
            ._normalize_values(
                update.sizes
            )
        )

        if (
            update.primary_asset_id
            is None
        ):
            return

        selected_asset = next(
            (
                asset
                for asset
                in item.selected_assets
                if (
                    asset.id
                    == update.primary_asset_id
                    and asset.is_selected
                )
            ),
            None,
        )

        if selected_asset is None:
            raise ValueError(
                (
                    "فایل انتخاب‌شده برای "
                    "تصویر اصلی معتبر نیست."
                )
            )

        for asset in item.selected_assets:
            asset.is_primary = (
                asset.id
                == selected_asset.id
            )

    @staticmethod
    def _normalize_values(
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        normalized: list[str] = []
        seen: set[str] = set()

        for value in values:
            cleaned = value.strip()
            key = cleaned.casefold()

            if (
                not cleaned
                or key in seen
            ):
                continue

            seen.add(key)
            normalized.append(
                cleaned
            )

        return tuple(
            normalized
        )
