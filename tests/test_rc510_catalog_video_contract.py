"""Contract tests for Selora catalog import extensions."""
from types import SimpleNamespace
from unittest.mock import Mock

from app.integrations.selora.client import SeloraApiClient, SeloraApiError
from app.integrations.selora.payload_mapper import SeloraPayloadMapper
from app.services.import_workspace_service import ImportWorkspaceItemUpdate, ImportWorkspaceService


def test_catalog_client_reads_scoped_choices():
    client = SeloraApiClient(base_url="https://selora.example", api_key="abc")
    client._request_json = Mock(return_value=({
        "categories": [{"id": 12, "name": "پوشاک", "slug": "pooshak"}],
        "subcategories": [{"id": 51, "category_id": 12, "name": "لباس"}],
    }, "req"))
    data = client.fetch_import_catalog()
    assert data["categories"][0]["id"] == 12
    assert data["subcategories"][0]["category_id"] == 12
    assert client._request_json.call_args.kwargs["method"] == "GET"


def test_invalid_catalog_body_is_rejected():
    client = SeloraApiClient(base_url="https://selora.example", api_key="abc")
    client._request_json = Mock(return_value=({"categories": {}, "subcategories": []}, "req"))
    try:
        client.fetch_import_catalog()
    except SeloraApiError:
        pass
    else:
        raise AssertionError("Invalid catalog response accepted")


def test_slug_and_parent_constraints_are_checked_locally():
    base = dict(
        item_id="a", is_selected=True, product_name="P", description="D",
        sale_price=10, list_price=20, stock=1, colors=(), sizes=(),
        primary_asset_id=None, category_id=None, subcategory_id=None,
    )
    for data in [dict(slug="Upper-CASE"), dict(slug="bad slug"),
                 dict(subcategory_id=7, category_id=None)]:
        update = ImportWorkspaceItemUpdate(**(base | data))
        try:
            ImportWorkspaceService._validate_update(update)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Invalid update accepted: {data}")


def test_payload_includes_video_and_extended_fields():
    product_data = SimpleNamespace(
        product_name="Name", description="Detail", benefits="Benefits",
        slug="sample-slug", category_id=12, subcategory_id=51,
        list_price=100, sale_price=90, stock=2, colors=[], sizes=[],
    )
    asset = SimpleNamespace(
        external_id="vid-1", asset_type="video", position=0,
        source_url="https://www.instagram.com/video-test", width=640,
        height=480, duration_seconds=9, asset_metadata={}, is_available=True,
    )
    selected = SimpleNamespace(asset=asset, is_selected=True, is_primary=False)
    media = SimpleNamespace(
        media_id="M1", shortcode="short", media_type="video", permalink="https://www.instagram.com/p/x/",
        caption="Caption", thumbnail_url="", published_at=None, like_count=None,
        comment_count=None, view_count=None, assets=[asset], is_available=True,
    )
    item = SimpleNamespace(
        media=media, product_data=product_data, selected_assets=[selected],
        is_selected=True, position=0,
    )
    body = SeloraPayloadMapper()._build_media_payload(item=item)
    assert body["draft"]["benefits"] == "Benefits"
    assert body["draft"]["slug"] == "sample-slug"
    assert body["draft"]["category_id"] == 12
    assert body["draft"]["subcategory_id"] == 51
    assert body["draft"]["selected_assets"][0]["asset_type"] == "video"
