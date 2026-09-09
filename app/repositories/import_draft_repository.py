"""
Compatibility module for Phase 1A.

New code must use ImportWorkspaceRepository.
"""

from app.repositories.import_workspace_repository import (
    ImportWorkspaceRepository,
)

ImportDraftRepository = ImportWorkspaceRepository

__all__ = [
    "ImportWorkspaceRepository",
    "ImportDraftRepository",
]
