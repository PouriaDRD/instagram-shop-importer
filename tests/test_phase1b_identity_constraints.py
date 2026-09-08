from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    InstagramAsset,
    InstagramMedia,
    InstagramSource,
    ImportAssetSelection,
    ImportWorkspace,
    ImportWorkspaceItem,
)
from app.repositories import InstagramSourceRepository


def _source(username: str = "identity_shop") -> InstagramSource:
    source = InstagramSource(username=username)
    db.session.add(source)
    db.session.commit()
    return source


def _media(
    source: InstagramSource,
    *,
    media_id: str = "media-1",
    shortcode: str = "short-1",
) -> InstagramMedia:
    media = InstagramMedia(
        source=source,
        media_id=media_id,
        shortcode=shortcode,
        media_type="image",
        permalink=f"https://instagram.com/p/{shortcode}/",
    )
    db.session.add(media)
    db.session.commit()
    return media


def test_repository_reuses_normalized_instagram_source(app) -> None:
    with app.app_context():
        repository = InstagramSourceRepository()

        first = repository.create(username="  @Same_Shop ")
        second = repository.create(username="same_shop")

        assert first.id == second.id
        assert InstagramSource.query.count() == 1


def test_source_username_is_unique_at_database_boundary(app) -> None:
    with app.app_context():
        _source("unique_shop")

        db.session.add(InstagramSource(username="unique_shop"))

        with pytest.raises(IntegrityError):
            db.session.commit()

        db.session.rollback()


def test_media_identity_is_unique_per_source(app) -> None:
    with app.app_context():
        source = _source()
        _media(source, media_id="same-media", shortcode="first")

        db.session.add(
            InstagramMedia(
                source=source,
                media_id="same-media",
                shortcode="second",
                media_type="image",
                permalink="https://instagram.com/p/second/",
            )
        )

        with pytest.raises(IntegrityError):
            db.session.commit()

        db.session.rollback()


def test_asset_identity_is_unique_per_media_type_position(app) -> None:
    with app.app_context():
        source = _source()
        media = _media(source)

        first = InstagramAsset(
            external_id="asset-1",
            asset_type="image",
            source_url="https://example.com/1.jpg",
            position=0,
        )
        media.assets.append(first)
        db.session.commit()

        duplicate = InstagramAsset(
            external_id="asset-2",
            asset_type="image",
            source_url="https://example.com/2.jpg",
            position=0,
        )
        media.assets.append(duplicate)

        with pytest.raises(IntegrityError):
            db.session.commit()

        db.session.rollback()


def test_only_one_workspace_is_allowed_per_source(app) -> None:
    with app.app_context():
        source = _source()

        first = ImportWorkspace(source_id=source.id)
        db.session.add(first)
        db.session.commit()

        db.session.add(ImportWorkspace(source_id=source.id))

        with pytest.raises(IntegrityError):
            db.session.commit()

        db.session.rollback()


def test_workspace_item_and_asset_selection_have_stable_identity(app) -> None:
    with app.app_context():
        source = _source()
        media = _media(source)

        asset = InstagramAsset(
            external_id="asset-1",
            asset_type="image",
            source_url="https://example.com/1.jpg",
            position=0,
        )
        media.assets.append(asset)
        db.session.commit()

        workspace = ImportWorkspace(source_id=source.id)
        db.session.add(workspace)
        db.session.flush()

        item = ImportWorkspaceItem(
            workspace_id=workspace.id,
            instagram_media_id=media.id,
            position=0,
        )
        db.session.add(item)
        db.session.flush()

        selection = ImportAssetSelection(
            workspace_item_id=item.id,
            instagram_asset_id=asset.id,
            position=0,
        )
        db.session.add(selection)
        db.session.commit()

        db.session.add(
            ImportWorkspaceItem(
                workspace_id=workspace.id,
                instagram_media_id=media.id,
                position=1,
            )
        )

        with pytest.raises(IntegrityError):
            db.session.commit()

        db.session.rollback()

        db.session.add(
            ImportAssetSelection(
                workspace_item_id=item.id,
                instagram_asset_id=asset.id,
                position=1,
            )
        )

        with pytest.raises(IntegrityError):
            db.session.commit()

        db.session.rollback()
