from __future__ import annotations

import logging
from dataclasses import dataclass

from app.models import CrawlSession
from app.models.import_draft import ImportDraft, ImportDraftItem, ImportDraftProductData
from app.repositories.import_draft_repository import ImportDraftRepository

logger = logging.getLogger("app")


@dataclass(frozen=True, slots=True)
class ImportDraftItemUpdate:
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


class ImportDraftService:
    def __init__(self, *, repository: ImportDraftRepository) -> None:
        self._repository = repository

    def create_from_session(
        self,
        *,
        crawl_session: CrawlSession,
        selected_media_ids: set[str],
        selected_asset_ids: set[str],
    ) -> ImportDraft:
        if crawl_session.status != "completed":
            raise ValueError(
                "Only completed crawl sessions can create an import draft."
            )
        if not selected_media_ids:
            raise ValueError("At least one media item must be selected.")

        available_media = {media.id: media for media in crawl_session.media}
        unknown_media_ids = selected_media_ids - available_media.keys()
        if unknown_media_ids:
            raise ValueError(
                "One or more selected media items do not belong to this crawl session."
            )

        draft = self._repository.create(crawl_session_id=crawl_session.id)

        try:
            selected_media = [
                media for media in crawl_session.media if media.id in selected_media_ids
            ]

            for item_position, media in enumerate(selected_media):
                draft_item = self._repository.add_item(
                    draft=draft,
                    crawled_media_id=media.id,
                    position=item_position,
                )
                self._repository.add_product_data(
                    item=draft_item,
                    description=(media.caption or "").strip(),
                )

                available_assets = [
                    asset for asset in media.assets if asset.id in selected_asset_ids
                ]
                for asset_position, asset in enumerate(available_assets):
                    self._repository.add_asset(
                        item=draft_item,
                        crawled_asset_id=asset.id,
                        position=asset_position,
                        is_primary=(asset_position == 0),
                    )

            self._repository.commit()
        except Exception:
            self._repository.rollback()
            logger.exception(
                "Failed to create import draft for crawl %s",
                crawl_session.id,
            )
            raise

        logger.info(
            "Import draft %s created from crawl %s with %s items",
            draft.id,
            crawl_session.id,
            len(selected_media),
        )
        return draft

    def ensure_product_data(self, *, draft: ImportDraft) -> None:
        created = False
        try:
            for item in draft.items:
                if item.product_data is None:
                    self._repository.add_product_data(
                        item=item,
                        description=(item.media.caption or "").strip(),
                    )
                    created = True
            if created:
                self._repository.commit()
        except Exception:
            self._repository.rollback()
            logger.exception("Failed to prepare product data for draft %s", draft.id)
            raise

    def update_draft(
        self,
        *,
        draft: ImportDraft,
        updates: list[ImportDraftItemUpdate],
    ) -> None:
        if draft.status != "draft":
            raise ValueError("Only drafts in draft status can be edited.")

        items_by_id = {item.id: item for item in draft.items}
        update_ids = {update.item_id for update in updates}
        unknown_ids = update_ids - items_by_id.keys()
        if unknown_ids:
            raise ValueError("One or more draft items do not belong to this draft.")

        try:
            for update in updates:
                item = items_by_id[update.item_id]
                product_data = item.product_data
                if product_data is None:
                    product_data = self._repository.add_product_data(
                        item=item,
                        description=(item.media.caption or "").strip(),
                    )

                self._validate_update(update)
                self._apply_update(
                    item=item,
                    product_data=product_data,
                    update=update,
                )

            self._repository.commit()
        except Exception:
            self._repository.rollback()
            logger.exception("Failed to update import draft %s", draft.id)
            raise

        logger.info("Import draft %s updated", draft.id)

    @staticmethod
    def _validate_update(update: ImportDraftItemUpdate) -> None:
        if len(update.product_name) > 255:
            raise ValueError("نام محصول نمی‌تواند بیشتر از ۲۵۵ کاراکتر باشد.")
        if update.sale_price is not None and update.sale_price < 0:
            raise ValueError("قیمت فروش نمی‌تواند منفی باشد.")
        if update.list_price is not None and update.list_price < 0:
            raise ValueError("قیمت قبل از تخفیف نمی‌تواند منفی باشد.")
        if (
            update.sale_price is not None
            and update.list_price is not None
            and update.sale_price > update.list_price
        ):
            raise ValueError("قیمت فروش نمی‌تواند از قیمت قبل از تخفیف بیشتر باشد.")
        if update.stock < 0:
            raise ValueError("موجودی نمی‌تواند منفی باشد.")

    @staticmethod
    def _apply_update(
        *,
        item: ImportDraftItem,
        product_data: ImportDraftProductData,
        update: ImportDraftItemUpdate,
    ) -> None:
        item.is_selected = update.is_selected
        product_data.product_name = update.product_name.strip()
        product_data.description = update.description.strip()
        product_data.sale_price = update.sale_price
        product_data.list_price = update.list_price
        product_data.stock = update.stock
        product_data.colors = list(ImportDraftService._normalize_values(update.colors))
        product_data.sizes = list(ImportDraftService._normalize_values(update.sizes))

        if update.primary_asset_id is None:
            return

        selected_asset = next(
            (
                asset
                for asset in item.selected_assets
                if asset.id == update.primary_asset_id and asset.is_selected
            ),
            None,
        )
        if selected_asset is None:
            raise ValueError("فایل انتخاب‌شده برای تصویر اصلی معتبر نیست.")

        for asset in item.selected_assets:
            asset.is_primary = asset.id == selected_asset.id

    @staticmethod
    def _normalize_values(values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            cleaned = value.strip()
            key = cleaned.casefold()
            if not cleaned or key in seen:
                continue
            seen.add(key)
            normalized.append(cleaned)
        return tuple(normalized)
