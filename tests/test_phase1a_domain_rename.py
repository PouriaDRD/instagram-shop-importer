from app.models import (
    CrawlSession,
    CrawledAsset,
    CrawledMedia,
    ImportDraft,
    ImportDraftAsset,
    ImportDraftItem,
    ImportDraftProductData,
    InstagramAsset,
    InstagramMedia,
    InstagramSource,
    ImportAssetSelection,
    ImportProductData,
    ImportWorkspace,
    ImportWorkspaceItem,
)
from app.repositories import (
    CrawlSessionRepository,
    ImportDraftRepository,
    InstagramSourceRepository,
    ImportWorkspaceRepository,
)
from app.services import (
    BackgroundCrawlRunner,
    BackgroundInstagramSyncRunner,
    CrawlService,
    ImportDraftService,
    InstagramSyncService,
    ImportWorkspaceService,
)


def test_model_compatibility_aliases_point_to_new_domain_classes():
    assert CrawlSession is InstagramSource
    assert CrawledMedia is InstagramMedia
    assert CrawledAsset is InstagramAsset
    assert ImportDraft is ImportWorkspace
    assert ImportDraftItem is ImportWorkspaceItem
    assert ImportDraftProductData is ImportProductData
    assert ImportDraftAsset is ImportAssetSelection


def test_repository_compatibility_aliases_point_to_new_classes():
    assert CrawlSessionRepository is InstagramSourceRepository
    assert ImportDraftRepository is ImportWorkspaceRepository


def test_service_compatibility_aliases_point_to_new_classes():
    assert CrawlService is InstagramSyncService
    assert ImportDraftService is ImportWorkspaceService
    assert BackgroundCrawlRunner is BackgroundInstagramSyncRunner


def test_legacy_table_names_are_preserved_in_phase1a():
    assert InstagramSource.__tablename__ == "crawl_sessions"
    assert InstagramMedia.__tablename__ == "crawled_media"
    assert InstagramAsset.__tablename__ == "crawled_assets"
    assert ImportWorkspace.__tablename__ == "import_drafts"
    assert ImportWorkspaceItem.__tablename__ == "import_draft_items"
    assert ImportProductData.__tablename__ == "import_draft_product_data"
    assert ImportAssetSelection.__tablename__ == "import_draft_assets"
