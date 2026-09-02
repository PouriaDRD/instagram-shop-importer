class ImporterError(Exception):
    pass


class CrawlerError(ImporterError):
    pass


class InstagramError(CrawlerError):
    pass


class InstagramProfileNotFoundError(InstagramError):
    pass


class InstagramPrivateProfileError(InstagramError):
    pass


class InstagramAuthenticationRequiredError(InstagramError):
    pass


class InstagramRateLimitedError(InstagramError):
    pass


class InstagramMediaFetchError(InstagramError):
    pass


class SeloraImportError(ImporterError):
    pass
