from __future__ import annotations

from types import SimpleNamespace

from app.extensions import db
from app.models import (
    InstagramAsset,
    InstagramMedia,
    ImportProductData,
    ImportWorkspace,
    ImportWorkspaceItem,
)
from app.repositories import InstagramSourceRepository


class _EnumValue:
    def __init__(self, value: str) -> None:
        self.value = value


def _asset(
    *,
    external_id: str,
    source_url: str,
    position: int = 0,
    asset_type: str = "image",
):
    return SimpleNamespace(
        external_id=external_id,
        asset_type=_EnumValue(asset_type),
        source_url=source_url,
        position=position,
        width=1000,
        height=1000,
        duration_seconds=None,
        metadata={"source": "test"},
    )


def _media(
    *,
    media_id: str,
    shortcode: str,
    caption: str,
    assets=(),
    position: int = 0,
):
    return SimpleNamespace(
        media_id=media_id,
        shortcode=shortcode,
        media_type=_EnumValue("image"),
        permalink=(
            f"https://instagram.com/p/{shortcode}/"
        ),
        caption=caption,
        thumbnail_url="",
        published_at=None,
        like_count=10,
        comment_count=2,
        view_count=None,
        raw_payload={"version": caption},
        assets=tuple(assets),
        position=position,
    )


def test_recrawl_updates_media_and_asset_in_place_and_preserves_workspace_edit(
    app,
) -> None:
    with app.app_context():
        repository = InstagramSourceRepository()
        source = repository.create(
            username="stable_shop"
        )

        repository.sync_media(
            session=source,
            media_items=(
                _media(
                    media_id="m1",
                    shortcode="abc",
                    caption="old caption",
                    assets=(
                        _asset(
                            external_id="a1",
                            source_url=(
                                "https://cdn.example/old.jpg"
                            ),
                        ),
                    ),
                ),
            ),
            full_sync=True,
        )

        media = InstagramMedia.query.one()
        asset = InstagramAsset.query.one()

        original_media_pk = media.id
        original_asset_pk = asset.id

        workspace = ImportWorkspace(
            source_id=source.id
        )
        db.session.add(workspace)
        db.session.flush()

        item = ImportWorkspaceItem(
            workspace_id=workspace.id,
            instagram_media_id=media.id,
            position=0,
        )
        db.session.add(item)
        db.session.flush()

        product_data = ImportProductData(
            workspace_item_id=item.id,
            product_name="operator edited title",
            description="operator edited description",
            sale_price=123,
            list_price=150,
            stock=4,
        )
        db.session.add(product_data)
        db.session.commit()

        repository.sync_media(
            session=source,
            media_items=(
                _media(
                    media_id="m1",
                    shortcode="abc",
                    caption="new caption",
                    assets=(
                        _asset(
                            external_id="a1-new",
                            source_url=(
                                "https://cdn.example/new.jpg"
                            ),
                        ),
                    ),
                ),
            ),
            full_sync=True,
        )

        refreshed_media = InstagramMedia.query.one()
        refreshed_asset = InstagramAsset.query.one()
        refreshed_product_data = (
            ImportProductData.query.one()
        )

        assert refreshed_media.id == original_media_pk
        assert refreshed_asset.id == original_asset_pk
        assert refreshed_media.caption == "new caption"
        assert (
            refreshed_asset.source_url
            == "https://cdn.example/new.jpg"
        )
        assert refreshed_media.is_available is True
        assert refreshed_asset.is_available is True
        assert refreshed_media.last_seen_at is not None
        assert refreshed_asset.last_seen_at is not None

        assert (
            refreshed_product_data.product_name
            == "operator edited title"
        )
        assert (
            refreshed_product_data.description
            == "operator edited description"
        )
        assert refreshed_product_data.sale_price == 123


def test_full_sync_marks_missing_media_unavailable_without_deleting_it(
    app,
) -> None:
    with app.app_context():
        repository = InstagramSourceRepository()
        source = repository.create(
            username="full_sync_shop"
        )

        repository.sync_media(
            session=source,
            media_items=(
                _media(
                    media_id="m1",
                    shortcode="one",
                    caption="one",
                ),
                _media(
                    media_id="m2",
                    shortcode="two",
                    caption="two",
                ),
            ),
            full_sync=True,
        )

        missing = InstagramMedia.query.filter_by(
            media_id="m2"
        ).one()

        missing_pk = missing.id

        repository.sync_media(
            session=source,
            media_items=(
                _media(
                    media_id="m1",
                    shortcode="one",
                    caption="one updated",
                ),
            ),
            full_sync=True,
        )

        missing = db.session.get(
            InstagramMedia,
            missing_pk,
        )

        assert missing is not None
        assert missing.is_available is False
        assert InstagramMedia.query.count() == 2


def test_partial_sync_does_not_mark_unseen_media_unavailable(
    app,
) -> None:
    with app.app_context():
        repository = InstagramSourceRepository()
        source = repository.create(
            username="partial_sync_shop"
        )

        repository.sync_media(
            session=source,
            media_items=(
                _media(
                    media_id="m1",
                    shortcode="one",
                    caption="one",
                ),
                _media(
                    media_id="m2",
                    shortcode="two",
                    caption="two",
                ),
            ),
            full_sync=True,
        )

        repository.sync_media(
            session=source,
            media_items=(
                _media(
                    media_id="m1",
                    shortcode="one",
                    caption="one newer",
                ),
            ),
            full_sync=False,
        )

        unseen = InstagramMedia.query.filter_by(
            media_id="m2"
        ).one()

        assert unseen.is_available is True


def test_missing_asset_is_marked_unavailable_not_deleted(
    app,
) -> None:
    with app.app_context():
        repository = InstagramSourceRepository()
        source = repository.create(
            username="asset_sync_shop"
        )

        repository.sync_media(
            session=source,
            media_items=(
                _media(
                    media_id="m1",
                    shortcode="abc",
                    caption="caption",
                    assets=(
                        _asset(
                            external_id="a1",
                            source_url="https://cdn.example/1.jpg",
                            position=0,
                        ),
                        _asset(
                            external_id="a2",
                            source_url="https://cdn.example/2.jpg",
                            position=1,
                        ),
                    ),
                ),
            ),
            full_sync=True,
        )

        second = InstagramAsset.query.filter_by(
            position=1
        ).one()
        second_pk = second.id

        repository.sync_media(
            session=source,
            media_items=(
                _media(
                    media_id="m1",
                    shortcode="abc",
                    caption="caption",
                    assets=(
                        _asset(
                            external_id="a1",
                            source_url="https://cdn.example/1-new.jpg",
                            position=0,
                        ),
                    ),
                ),
            ),
            full_sync=True,
        )

        second = db.session.get(
            InstagramAsset,
            second_pk,
        )

        assert second is not None
        assert second.is_available is False
        assert InstagramAsset.query.count() == 2
