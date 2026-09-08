from app.models.instagram_source import InstagramSource
from app.models.import_workspace import (
    ImportAssetSelection,
    ImportProductData,
    ImportWorkspace,
    ImportWorkspaceItem,
)
from app.models.media import (
    InstagramAsset,
    InstagramMedia,
)

# Temporary compatibility aliases.
CrawlSession = InstagramSource
CrawledAsset = InstagramAsset
CrawledMedia = InstagramMedia
ImportDraft = ImportWorkspace
ImportDraftAsset = ImportAssetSelection
ImportDraftItem = ImportWorkspaceItem
ImportDraftProductData = ImportProductData

__all__ = [
    "InstagramSource",
    "InstagramMedia",
    "InstagramAsset",
    "ImportWorkspace",
    "ImportWorkspaceItem",
    "ImportProductData",
    "ImportAssetSelection",
    "CrawlSession",
    "CrawledAsset",
    "CrawledMedia",
    "ImportDraft",
    "ImportDraftAsset",
    "ImportDraftItem",
    "ImportDraftProductData",
]
