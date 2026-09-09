from __future__ import annotations

from app.extensions import db
from app.models import (
    InstagramAsset,
    InstagramMedia,
)
from app.models.import_workspace import (
    ImportWorkspace,
    LocalSyncStatus,
    RemoteWorkflowStatus,
)
from app.repositories import (
    CrawlSessionRepository,
    ImportDraftRepository,
)
from app.services.import_draft_service import (
    ImportDraftService,
)


def test_synced_workspace_remains_same_workspace_on_revisit(
    app,
) -> None:
    with app.app_context():
        source_repository = (
            CrawlSessionRepository()
        )
        source = source_repository.create(
            username="workspace_revisit"
        )
        source.status = "completed"

        media = InstagramMedia(
            source=source,
            media_id="ig-1",
            shortcode="abc",
            media_type="image",
            permalink=(
                "https://instagram.com/p/abc/"
            ),
        )
        db.session.add(media)
        db.session.flush()

        asset = InstagramAsset(
            external_id="asset-1",
            asset_type="image",
            source_url=(
                "https://example.com/1.jpg"
            ),
            position=0,
        )
        media.assets.append(asset)
        db.session.commit()

        repository = ImportDraftRepository()
        service = ImportDraftService(
            repository=repository
        )

        first = (
            service.create_or_update_from_session(
                crawl_session=source,
                selected_media_ids={
                    media.id,
                },
                selected_asset_ids={
                    asset.id,
                },
            )
        )

        workspace_id = first.id

        service.mark_sent(
            draft=first
        )

        revisited = (
            repository.get_current_for_session(
                crawl_session_id=source.id
            )
        )

        assert revisited is not None
        assert revisited.id == workspace_id
        assert (
            revisited.local_sync_status
            == LocalSyncStatus.SYNCED.value
        )

        second = (
            service.create_or_update_from_session(
                crawl_session=source,
                selected_media_ids={
                    media.id,
                },
                selected_asset_ids={
                    asset.id,
                },
            )
        )

        assert second.id == workspace_id
        assert ImportWorkspace.query.count() == 1
        assert (
            second.local_sync_status
            == LocalSyncStatus.PENDING.value
        )


def test_remote_locked_workspace_is_read_only_when_status_is_known(
    app,
) -> None:
    with app.app_context():
        source_repository = (
            CrawlSessionRepository()
        )
        source = source_repository.create(
            username="locked_workspace"
        )
        source.status = "completed"
        db.session.commit()

        workspace = ImportWorkspace(
            source_id=source.id,
            remote_workflow_status=(
                RemoteWorkflowStatus
                .IMPORTED
                .value
            ),
        )
        db.session.add(workspace)
        db.session.commit()

        service = ImportDraftService(
            repository=ImportDraftRepository()
        )

        try:
            service.update_draft(
                draft=workspace,
                updates=[],
            )
        except ValueError as exc:
            assert "فقط قابل مشاهده" in str(exc)
        else:
            raise AssertionError(
                "Locked workspace accepted a mutation."
            )
