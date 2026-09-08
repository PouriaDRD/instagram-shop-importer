"""
Compatibility module for Phase 1A.

New code must use ImportWorkspaceService.
"""

from app.services.import_workspace_service import (
    ImportWorkspaceItemUpdate,
    ImportWorkspaceService,
)

ImportDraftItemUpdate = ImportWorkspaceItemUpdate
ImportDraftService = ImportWorkspaceService

__all__ = [
    "ImportWorkspaceItemUpdate",
    "ImportWorkspaceService",
    "ImportDraftItemUpdate",
    "ImportDraftService",
]
