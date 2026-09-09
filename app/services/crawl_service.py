"""
Compatibility module for Phase 1A.

New code must use InstagramSyncService.
"""

from app.services.instagram_sync_service import (
    InstagramSyncService,
)

CrawlService = InstagramSyncService

__all__ = [
    "InstagramSyncService",
    "CrawlService",
]
