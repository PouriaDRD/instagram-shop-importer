"""
Compatibility module for Phase 1A.

New code must import InstagramSource from app.models.instagram_source.
The alias remains temporarily so existing imports/tests keep working while
the refactor is rolled out incrementally.
"""

from app.models.instagram_source import InstagramSource

CrawlSession = InstagramSource

__all__ = [
    "InstagramSource",
    "CrawlSession",
]
