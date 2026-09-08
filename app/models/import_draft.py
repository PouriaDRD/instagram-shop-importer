"""
Compatibility module for Phase 1A.

New code should use app.models.import_workspace.
"""

from app.models.import_workspace import (
    ImportAssetSelection,
    ImportProductData,
    ImportWorkspace,
    ImportWorkspaceItem,
)

ImportDraft = ImportWorkspace
ImportDraftAsset = ImportAssetSelection
ImportDraftItem = ImportWorkspaceItem
ImportDraftProductData = ImportProductData

__all__ = [
    "ImportWorkspace",
    "ImportWorkspaceItem",
    "ImportProductData",
    "ImportAssetSelection",
    "ImportDraft",
    "ImportDraftItem",
    "ImportDraftProductData",
    "ImportDraftAsset",
]
