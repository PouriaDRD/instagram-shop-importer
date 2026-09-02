from __future__ import annotations


class ImporterError(Exception):
    """Base exception for importer failures."""


class CrawlerError(ImporterError):
    """Base exception for crawler failures."""


class InstagramError(CrawlerError):
    """Base exception for Instagram failures."""


class InstagramProviderError(InstagramError):
    """Generic Instagram provider failure."""


class InstagramProfileNotFoundError(InstagramError):
    """Instagram profile does not exist."""


class InstagramProfileUnavailableError(InstagramError):
    """Instagram profile cannot currently be accessed."""


class InstagramPrivateProfileError(InstagramError):
    """Instagram profile is private."""


class InstagramAuthenticationRequiredError(InstagramError):
    """Instagram requires authentication."""


class InstagramRateLimitedError(InstagramError):
    """Instagram rate-limited the crawler."""


class InstagramFetchTimeoutError(InstagramError):
    """Instagram request timed out."""


class InstagramMediaFetchError(InstagramError):
    """A media item could not be fetched."""
