from __future__ import annotations

from datetime import datetime, timezone
from unittest import TestCase
from unittest.mock import Mock

import requests

from app.integrations.selora.client import (
    SeloraApiClient,
    SeloraApiNetworkError,
)
from app.integrations.selora.payload_mapper import (
    SeloraPayloadMapper,
)
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


class SeloraApiClientTests(TestCase):
    def test_send_import_uses_generic_api_key_header(self) -> None:
        response = Mock(spec=requests.Response)
        response.status_code = 201
        response.headers = {
            "X-Request-ID": "req-1",
        }
        response.json.return_value = {
            "ok": True,
            "session": {
                "id": "session-1",
                "replayed": False,
                "media_count": 2,
                "draft_count": 2,
            },
        }

        http = Mock(spec=requests.Session)
        http.post.return_value = response

        client = SeloraApiClient(
            base_url="http://127.0.0.1:8000/",
            api_key="selora_test_secret",
            http_session=http,
        )

        result = client.send_import(
            payload={
                "external_import_id": "draft-1",
            },
            request_id="req-1",
        )

        self.assertEqual(
            result.session_id,
            "session-1",
        )

        _, kwargs = http.post.call_args

        self.assertEqual(
            kwargs["headers"]["X-API-Key"],
            "selora_test_secret",
        )

        self.assertEqual(
            kwargs["headers"]["X-Request-ID"],
            "req-1",
        )

    def test_network_failure_is_retry_safe_error(self) -> None:
        http = Mock(spec=requests.Session)
        http.post.side_effect = requests.Timeout()

        client = SeloraApiClient(
            base_url="http://127.0.0.1:8000",
            api_key="key",
            http_session=http,
        )

        with self.assertRaises(SeloraApiNetworkError):
            client.send_import(
                payload={
                    "external_import_id": "draft-1",
                },
                request_id="draft-1",
            )


class SeloraPayloadMapperTests(TestCase):
    def test_mapper_preserves_nullable_prices_and_maps_options(
        self,
    ) -> None:
        crawl_session = CrawlSession(
            username="sample_shop",
            status="completed",
        )
        crawl_session.id = "crawl-1"
        crawl_session.full_name = "Sample Shop"
        crawl_session.biography = "bio"
        crawl_session.profile_picture_url = None
        crawl_session.followers_count = 100
        crawl_session.following_count = 10
        crawl_session.instagram_media_count = 5
        crawl_session.is_private = False

        media = CrawledMedia(
            session=crawl_session,
            media_id="media-1",
            shortcode="ABC",
            media_type="image",
            permalink="https://instagram.com/p/ABC/",
            caption="caption",
            thumbnail_url=None,
            published_at=datetime(
                2026,
                9,
                8,
                tzinfo=timezone.utc,
            ),
            like_count=1,
            comment_count=2,
            view_count=None,
            position=0,
            raw_payload={},
        )
        media.id = "media-row-1"

        asset = CrawledAsset(
            external_id="asset-1",
            asset_type="image",
            source_url="https://example.com/a.jpg",
            position=0,
            width=100,
            height=100,
            duration_seconds=None,
            asset_metadata={},
        )
        asset.id = "asset-row-1"
        asset.media = media

        draft = ImportDraft(
            crawl_session_id=crawl_session.id,
        )
        draft.id = "550e8400-e29b-41d4-a716-446655440000"

        item = ImportDraftItem(
            draft_id=draft.id,
            crawled_media_id=media.id,
            position=0,
            is_selected=True,
        )
        item.id = "draft-item-1"
        item.media = media

        product_data = ImportDraftProductData(
            draft_item_id=item.id,
            product_name="Test Product",
            description="Description",
            sale_price=None,
            list_price=None,
            stock=0,
            colors=[
                "مشکی",
                "سفید",
            ],
            sizes=[
                "M",
                "L",
            ],
        )
        item.product_data = product_data

        selected_asset = ImportDraftAsset(
            draft_item_id=item.id,
            crawled_asset_id=asset.id,
            position=0,
            is_selected=True,
            is_primary=True,
        )
        selected_asset.id = "selected-asset-1"
        selected_asset.asset = asset

        item.selected_assets.append(selected_asset)
        draft.items.append(item)

        payload = SeloraPayloadMapper().build_import_payload(
            draft=draft,
            crawl_session=crawl_session,
        )

        product_draft = payload["media"][0]["draft"]

        self.assertIsNone(product_draft["price_with_discount"])

        self.assertIsNone(product_draft["price_without_discount"])

        self.assertEqual(
            [option["kind"] for option in product_draft["options"]],
            [
                "color",
                "size",
            ],
        )

        self.assertEqual(
            payload["external_import_id"],
            draft.id,
        )
