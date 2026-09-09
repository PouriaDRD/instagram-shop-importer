from app.repositories.instagram_source_repository import (
    InstagramSourceRepository,
)
from app.repositories.import_workspace_repository import (
    ImportWorkspaceRepository,
)

# Temporary compatibility aliases.
CrawlSessionRepository = InstagramSourceRepository
ImportDraftRepository = ImportWorkspaceRepository

__all__ = [
    "InstagramSourceRepository",
    "ImportWorkspaceRepository",
    "CrawlSessionRepository",
    "ImportDraftRepository",
]
