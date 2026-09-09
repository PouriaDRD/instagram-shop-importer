"""
Compatibility module for Phase 1A.

New code must use InstagramSourceRepository.
"""

from app.repositories.instagram_source_repository import (
    InstagramSourceRepository,
)

CrawlSessionRepository = InstagramSourceRepository

__all__ = [
    "InstagramSourceRepository",
    "CrawlSessionRepository",
]
