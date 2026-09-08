from __future__ import annotations

from unittest import TestCase

from app.models import CrawlSession
from app.models.import_draft import (
    ImportDraft,
    ImportDraftAsset,
    ImportDraftItem,
    ImportDraftProductData,
)
from app.models.media import (
    CrawledAsset,
    CrawledMedia,
)
from app.services.import_validation_service import (
    ImportDraftValidationService,
    ImportIssueSeverity,
)


def _build_item(
    *,
    product_name: str = "Product",
    sale_price: int | None = 100,
    list_price: int | None = 120,
    with_asset: bool = True,
    with_primary: bool = True,
) -> tuple[ImportDraft, ImportDraftItem]:
    crawl = CrawlSession(
        username="sample_shop",
        status="completed",
    )
    crawl.id = "crawl-1"

    media = CrawledMedia(
        session=crawl,
        media_id="ig-1",
        shortcode="ABC",
        media_type="image",
        permalink="https://instagram.com/p/ABC/",
        position=0,
    )
    media.id = "media-1"

    draft = ImportDraft(
        crawl_session_id=crawl.id,
    )
    draft.id = "draft-1"

    item = ImportDraftItem(
        draft_id=draft.id,
        crawled_media_id=media.id,
        position=0,
        is_selected=True,
    )
    item.id = "item-1"
    item.media = media
    item.product_data = ImportDraftProductData(
        draft_item_id=item.id,
        product_name=product_name,
        description="Description",
        sale_price=sale_price,
        list_price=list_price,
        stock=0,
    )

    if with_asset:
        asset = CrawledAsset(
            external_id="asset-1",
            asset_type="image",
            source_url="https://example.com/1.jpg",
            position=0,
        )
        asset.id = "asset-1"
        asset.media = media

        link = ImportDraftAsset(
            draft_item_id=item.id,
            crawled_asset_id=asset.id,
            position=0,
            is_selected=True,
            is_primary=with_primary,
        )
        link.id = "link-1"
        link.asset = asset
        item.selected_assets.append(link)

    draft.items.append(item)

    return draft, item


class ImportDraftValidationServiceTests(TestCase):
    def test_complete_item_is_ready_and_sendable(self) -> None:
        draft, _ = _build_item()

        result = ImportDraftValidationService().validate(draft=draft)

        self.assertTrue(result.can_send)
        self.assertEqual(result.ready_item_count, 1)
        self.assertEqual(result.error_count, 0)
        self.assertEqual(result.warning_count, 0)

    def test_missing_name_blocks_send(self) -> None:
        draft, _ = _build_item(
            product_name="",
        )

        result = ImportDraftValidationService().validate(draft=draft)

        self.assertFalse(result.can_send)
        self.assertEqual(result.blocked_item_count, 1)
        self.assertEqual(
            result.items[0].issues[0].severity,
            ImportIssueSeverity.ERROR,
        )

    def test_missing_selected_asset_blocks_send(self) -> None:
        draft, _ = _build_item(
            with_asset=False,
        )

        result = ImportDraftValidationService().validate(draft=draft)

        self.assertFalse(result.can_send)
        self.assertTrue(
            any(
                issue.code == "missing_selected_asset"
                and issue.severity == ImportIssueSeverity.ERROR
                for issue in result.items[0].issues
            )
        )

    def test_missing_price_is_warning_not_error(self) -> None:
        draft, _ = _build_item(
            sale_price=None,
            list_price=None,
        )

        result = ImportDraftValidationService().validate(draft=draft)

        self.assertTrue(result.can_send)
        self.assertEqual(result.warning_count, 1)
        self.assertEqual(result.error_count, 0)
        self.assertTrue(
            any(
                issue.code == "missing_price"
                and issue.severity == ImportIssueSeverity.WARNING
                for issue in result.items[0].issues
            )
        )

    def test_missing_primary_asset_is_warning(self) -> None:
        draft, _ = _build_item(
            with_primary=False,
        )

        result = ImportDraftValidationService().validate(draft=draft)

        self.assertTrue(result.can_send)
        self.assertEqual(result.warning_count, 1)
        self.assertTrue(
            any(
                issue.code == "missing_primary_asset"
                for issue in result.items[0].issues
            )
        )

    def test_deselected_items_are_ignored(self) -> None:
        draft, item = _build_item(
            product_name="",
            with_asset=False,
        )
        item.is_selected = False

        result = ImportDraftValidationService().validate(draft=draft)

        self.assertFalse(result.can_send)
        self.assertEqual(result.selected_count, 0)
        self.assertEqual(result.items, ())
