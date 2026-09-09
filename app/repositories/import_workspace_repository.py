from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models.import_workspace import (
    ImportAssetSelection,
    ImportProductData,
    ImportWorkspace,
    ImportWorkspaceItem,
)


class ImportWorkspaceRepository:
    def create(
        self,
        *,
        source_id: str | None = None,
        crawl_session_id: str | None = None,
    ) -> ImportWorkspace:
        effective_source_id = (
            source_id or crawl_session_id
        )

        if not effective_source_id:
            raise ValueError(
                "Import workspace source is required."
            )

        workspace = ImportWorkspace(
            source_id=effective_source_id,
        )

        db.session.add(workspace)
        db.session.flush()

        return workspace

    def add_item(
        self,
        *,
        workspace: ImportWorkspace | None = None,
        draft: ImportWorkspace | None = None,
        instagram_media_id: str | None = None,
        crawled_media_id: str | None = None,
        position: int,
    ) -> ImportWorkspaceItem:
        target_workspace = workspace or draft
        effective_media_id = (
            instagram_media_id or crawled_media_id
        )

        if target_workspace is None:
            raise ValueError(
                "Import workspace is required."
            )

        if not effective_media_id:
            raise ValueError(
                "Instagram media id is required."
            )

        item = ImportWorkspaceItem(
            workspace_id=target_workspace.id,
            instagram_media_id=effective_media_id,
            position=position,
        )

        db.session.add(item)
        db.session.flush()

        return item

    def add_product_data(
        self,
        *,
        item: ImportWorkspaceItem,
        description: str = "",
    ) -> ImportProductData:
        product_data = ImportProductData(
            workspace_item_id=item.id,
            description=description,
        )

        db.session.add(product_data)
        db.session.flush()

        return product_data

    def add_asset(
        self,
        *,
        item: ImportWorkspaceItem,
        instagram_asset_id: str | None = None,
        crawled_asset_id: str | None = None,
        position: int,
        is_primary: bool,
    ) -> ImportAssetSelection:
        effective_asset_id = (
            instagram_asset_id or crawled_asset_id
        )

        if not effective_asset_id:
            raise ValueError(
                "Instagram asset id is required."
            )

        selection = ImportAssetSelection(
            workspace_item_id=item.id,
            instagram_asset_id=effective_asset_id,
            position=position,
            is_selected=True,
            is_primary=is_primary,
        )

        db.session.add(selection)
        db.session.flush()

        return selection

    def get(
        self,
        *,
        workspace_id: str | None = None,
        draft_id: str | None = None,
    ) -> ImportWorkspace | None:
        effective_id = workspace_id or draft_id

        if not effective_id:
            return None

        statement = (
            select(ImportWorkspace)
            .where(
                ImportWorkspace.id
                == effective_id
            )
            .options(
                *self._eager_load_options()
            )
        )

        return db.session.scalar(statement)

    def get_for_source(
        self,
        *,
        source_id: str,
    ) -> ImportWorkspace | None:
        """
        Return the persistent workspace for a source regardless of legacy
        draft/sent status.

        Historical duplicate workspaces are handled in Phase 1B.
        Until then the oldest row is treated as canonical.
        """

        statement = (
            select(ImportWorkspace)
            .where(
                ImportWorkspace.source_id
                == source_id
            )
            .order_by(
                ImportWorkspace.created_at.asc(),
                ImportWorkspace.id.asc(),
            )
            .limit(1)
            .options(
                *self._eager_load_options()
            )
        )

        return db.session.scalar(statement)

    def get_current_for_session(
        self,
        *,
        crawl_session_id: str,
    ) -> ImportWorkspace | None:
        """
        Legacy compatibility.

        Unlike the old implementation this does NOT filter status='draft';
        the same persistent workspace is reused after a previous send.
        """

        return self.get_for_source(
            source_id=crawl_session_id
        )

    def commit(self) -> None:
        db.session.commit()

    def rollback(self) -> None:
        db.session.rollback()

    @staticmethod
    def _eager_load_options():
        return (
            selectinload(
                ImportWorkspace.items
            ).selectinload(
                ImportWorkspaceItem.media
            ),
            selectinload(
                ImportWorkspace.items
            ).selectinload(
                ImportWorkspaceItem.product_data
            ),
            selectinload(
                ImportWorkspace.items
            )
            .selectinload(
                ImportWorkspaceItem.selected_assets
            )
            .selectinload(
                ImportAssetSelection.asset
            ),
        )
