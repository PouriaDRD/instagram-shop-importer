from __future__ import annotations

from unittest import TestCase
from unittest.mock import Mock

from app.models import CrawlSession
from app.models.import_draft import (
    ImportDraft,
    ImportDraftAsset,
    ImportDraftItem,
    ImportDraftProductData,
)
from app.models.import_workspace import (
    LocalSyncStatus,
)
from app.models.media import (
    CrawledAsset,
    CrawledMedia,
)
from app.repositories.import_draft_repository import (
    ImportDraftRepository,
)
from app.services.import_draft_service import (
    ImportDraftService,
)


def _build_completed_crawl() -> tuple[
    CrawlSession,
    CrawledMedia,
    CrawledMedia,
    CrawledAsset,
    CrawledAsset,
]:
    crawl = CrawlSession(
        username="sample_shop",
        status="completed",
    )
    crawl.id = "crawl-1"

    media_one = CrawledMedia(
        session=crawl,
        media_id="ig-media-1",
        shortcode="AAA",
        media_type="image",
        permalink="https://instagram.com/p/AAA/",
        position=0,
    )
    media_one.id = "media-1"

    media_two = CrawledMedia(
        session=crawl,
        media_id="ig-media-2",
        shortcode="BBB",
        media_type="image",
        permalink="https://instagram.com/p/BBB/",
        position=1,
    )
    media_two.id = "media-2"

    asset_one = CrawledAsset(
        external_id="asset-1",
        asset_type="image",
        source_url="https://example.com/1.jpg",
        position=0,
    )
    asset_one.id = "asset-1"
    asset_one.media = media_one

    asset_two = CrawledAsset(
        external_id="asset-2",
        asset_type="image",
        source_url="https://example.com/2.jpg",
        position=0,
    )
    asset_two.id = "asset-2"
    asset_two.media = media_two

    return (
        crawl,
        media_one,
        media_two,
        asset_one,
        asset_two,
    )


class ImportDraftLifecycleTests(TestCase):
    def test_reuses_current_draft_and_preserves_product_edits(
        self,
    ) -> None:
        (
            crawl,
            media_one,
            _,
            asset_one,
            _,
        ) = _build_completed_crawl()

        draft = ImportDraft(
            crawl_session_id=crawl.id,
        )
        draft.id = "draft-1"

        item = ImportDraftItem(
            draft_id=draft.id,
            crawled_media_id=media_one.id,
            position=0,
        )
        item.id = "item-1"
        item.media = media_one

        product_data = ImportDraftProductData(
            draft_item_id=item.id,
            product_name="Edited name",
            description="Edited description",
            sale_price=123,
            list_price=150,
            stock=4,
        )
        item.product_data = product_data

        selected_asset = ImportDraftAsset(
            draft_item_id=item.id,
            crawled_asset_id=asset_one.id,
            position=0,
            is_selected=True,
            is_primary=True,
        )
        selected_asset.id = "selected-asset-1"
        selected_asset.asset = asset_one
        item.selected_assets.append(
            selected_asset
        )
        draft.items.append(item)

        repository = Mock(
            spec=ImportDraftRepository
        )
        repository.get_current_for_session.return_value = (
            draft
        )

        service = ImportDraftService(
            repository=repository
        )

        result = (
            service.create_or_update_from_session(
                crawl_session=crawl,
                selected_media_ids={
                    media_one.id,
                },
                selected_asset_ids={
                    asset_one.id,
                },
            )
        )

        self.assertIs(
            result,
            draft,
        )
        self.assertEqual(
            result.id,
            "draft-1",
        )
        self.assertEqual(
            item.product_data.product_name,
            "Edited name",
        )
        self.assertEqual(
            item.product_data.sale_price,
            123,
        )

        repository.create.assert_not_called()
        repository.add_product_data.assert_not_called()
        repository.commit.assert_called_once_with()

    def test_back_selection_updates_same_draft_without_deleting_old_item(
        self,
    ) -> None:
        (
            crawl,
            media_one,
            media_two,
            asset_one,
            asset_two,
        ) = _build_completed_crawl()

        draft = ImportDraft(
            crawl_session_id=crawl.id,
        )
        draft.id = "draft-1"

        item_one = ImportDraftItem(
            draft_id=draft.id,
            crawled_media_id=media_one.id,
            position=0,
            is_selected=True,
        )
        item_one.id = "item-1"
        item_one.media = media_one
        item_one.product_data = (
            ImportDraftProductData(
                draft_item_id=item_one.id,
                product_name="Keep my edit",
            )
        )

        link_one = ImportDraftAsset(
            draft_item_id=item_one.id,
            crawled_asset_id=asset_one.id,
            position=0,
            is_selected=True,
            is_primary=True,
        )
        link_one.id = "link-1"
        link_one.asset = asset_one
        item_one.selected_assets.append(
            link_one
        )

        item_two = ImportDraftItem(
            draft_id=draft.id,
            crawled_media_id=media_two.id,
            position=1,
            is_selected=True,
        )
        item_two.id = "item-2"
        item_two.media = media_two
        item_two.product_data = (
            ImportDraftProductData(
                draft_item_id=item_two.id,
                product_name="Second product",
            )
        )

        link_two = ImportDraftAsset(
            draft_item_id=item_two.id,
            crawled_asset_id=asset_two.id,
            position=0,
            is_selected=True,
            is_primary=True,
        )
        link_two.id = "link-2"
        link_two.asset = asset_two
        item_two.selected_assets.append(
            link_two
        )

        draft.items.extend(
            [
                item_one,
                item_two,
            ]
        )

        repository = Mock(
            spec=ImportDraftRepository
        )
        repository.get_current_for_session.return_value = (
            draft
        )

        service = ImportDraftService(
            repository=repository
        )

        service.create_or_update_from_session(
            crawl_session=crawl,
            selected_media_ids={
                media_one.id,
            },
            selected_asset_ids={
                asset_one.id,
            },
        )

        self.assertTrue(
            item_one.is_selected
        )
        self.assertFalse(
            item_two.is_selected
        )
        self.assertEqual(
            item_one.product_data.product_name,
            "Keep my edit",
        )
        self.assertIn(
            item_two,
            draft.items,
        )

    def test_new_selection_after_back_is_added_to_current_draft(
        self,
    ) -> None:
        (
            crawl,
            media_one,
            media_two,
            asset_one,
            asset_two,
        ) = _build_completed_crawl()

        draft = ImportDraft(
            crawl_session_id=crawl.id,
        )
        draft.id = "draft-1"

        item_one = ImportDraftItem(
            draft_id=draft.id,
            crawled_media_id=media_one.id,
            position=0,
        )
        item_one.id = "item-1"
        item_one.media = media_one
        item_one.product_data = (
            ImportDraftProductData(
                draft_item_id=item_one.id,
                product_name="Existing edit",
            )
        )
        draft.items.append(
            item_one
        )

        repository = Mock(
            spec=ImportDraftRepository
        )
        repository.get_current_for_session.return_value = (
            draft
        )

        def add_item(
            *,
            draft: ImportDraft,
            crawled_media_id: str,
            position: int,
        ) -> ImportDraftItem:
            created = ImportDraftItem(
                draft_id=draft.id,
                crawled_media_id=crawled_media_id,
                position=position,
            )
            created.id = "item-2"
            created.media = media_two
            draft.items.append(
                created
            )
            return created

        def add_product_data(
            *,
            item: ImportDraftItem,
            description: str = "",
        ) -> ImportDraftProductData:
            created = (
                ImportDraftProductData(
                    draft_item_id=item.id,
                    description=description,
                )
            )
            item.product_data = created
            return created

        def add_asset(
            *,
            item: ImportDraftItem,
            crawled_asset_id: str,
            position: int,
            is_primary: bool,
        ) -> ImportDraftAsset:
            created = ImportDraftAsset(
                draft_item_id=item.id,
                crawled_asset_id=crawled_asset_id,
                position=position,
                is_selected=True,
                is_primary=is_primary,
            )
            created.id = "link-new"
            created.asset = (
                asset_one
                if (
                    crawled_asset_id
                    == asset_one.id
                )
                else asset_two
            )
            item.selected_assets.append(
                created
            )
            return created

        repository.add_item.side_effect = (
            add_item
        )
        repository.add_product_data.side_effect = (
            add_product_data
        )
        repository.add_asset.side_effect = (
            add_asset
        )

        service = ImportDraftService(
            repository=repository
        )

        result = (
            service.create_or_update_from_session(
                crawl_session=crawl,
                selected_media_ids={
                    media_one.id,
                    media_two.id,
                },
                selected_asset_ids={
                    asset_one.id,
                    asset_two.id,
                },
            )
        )

        self.assertEqual(
            result.id,
            "draft-1",
        )
        self.assertEqual(
            len(result.items),
            2,
        )
        self.assertEqual(
            (
                result.items[0]
                .product_data
                .product_name
            ),
            "Existing edit",
        )
        self.assertEqual(
            result.items[1].crawled_media_id,
            media_two.id,
        )

    def test_mark_sent_marks_sync_without_closing_workspace(
        self,
    ) -> None:
        draft = ImportDraft(
            crawl_session_id="crawl-1",
        )
        draft.id = "draft-1"

        repository = Mock(
            spec=ImportDraftRepository
        )

        service = ImportDraftService(
            repository=repository
        )

        service.mark_sent(
            draft=draft
        )

        self.assertEqual(
            draft.status,
            "draft",
        )
        self.assertEqual(
            draft.local_sync_status,
            LocalSyncStatus.SYNCED.value,
        )
        self.assertIsNotNone(
            draft.last_synced_at
        )
        repository.commit.assert_called_once_with()

    def test_edit_after_successful_sync_marks_workspace_pending_again(
        self,
    ) -> None:
        draft = ImportDraft(
            crawl_session_id="crawl-1",
            local_sync_status=(
                LocalSyncStatus.SYNCED.value
            ),
        )
        draft.id = "draft-1"

        repository = Mock(
            spec=ImportDraftRepository
        )

        service = ImportDraftService(
            repository=repository
        )

        service.update_draft(
            draft=draft,
            updates=[],
        )

        self.assertEqual(
            draft.status,
            "draft",
        )
        self.assertEqual(
            draft.local_sync_status,
            LocalSyncStatus.PENDING.value,
        )
        repository.commit.assert_called_once_with()
