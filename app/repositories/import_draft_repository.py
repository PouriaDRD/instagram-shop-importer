from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models.import_draft import (
    ImportDraft,
    ImportDraftAsset,
    ImportDraftItem,
    ImportDraftProductData,
)


class ImportDraftRepository:
    def create(self, *, crawl_session_id: str) -> ImportDraft:
        draft = ImportDraft(crawl_session_id=crawl_session_id)
        db.session.add(draft)
        db.session.flush()
        return draft

    def add_item(
        self,
        *,
        draft: ImportDraft,
        crawled_media_id: str,
        position: int,
    ) -> ImportDraftItem:
        item = ImportDraftItem(
            draft_id=draft.id,
            crawled_media_id=crawled_media_id,
            position=position,
        )
        db.session.add(item)
        db.session.flush()
        return item

    def add_product_data(
        self,
        *,
        item: ImportDraftItem,
        description: str = "",
    ) -> ImportDraftProductData:
        product_data = ImportDraftProductData(
            draft_item_id=item.id,
            description=description,
        )
        db.session.add(product_data)
        db.session.flush()
        return product_data

    def add_asset(
        self,
        *,
        item: ImportDraftItem,
        crawled_asset_id: str,
        position: int,
        is_primary: bool,
    ) -> ImportDraftAsset:
        asset = ImportDraftAsset(
            draft_item_id=item.id,
            crawled_asset_id=crawled_asset_id,
            position=position,
            is_selected=True,
            is_primary=is_primary,
        )
        db.session.add(asset)
        return asset

    def get(self, *, draft_id: str) -> ImportDraft | None:
        statement = (
            select(ImportDraft)
            .where(ImportDraft.id == draft_id)
            .options(
                selectinload(ImportDraft.items).selectinload(ImportDraftItem.media),
                selectinload(ImportDraft.items).selectinload(
                    ImportDraftItem.product_data
                ),
                selectinload(ImportDraft.items)
                .selectinload(ImportDraftItem.selected_assets)
                .selectinload(ImportDraftAsset.asset),
            )
        )
        return db.session.scalar(statement)

    def commit(self) -> None:
        db.session.commit()

    def rollback(self) -> None:
        db.session.rollback()
