class TikTokScraperError(Exception):
    """Base class for all errors raised while scraping TikTok."""


class TikTokClientGetError(TikTokScraperError):
    """Raised when GET request to TikTok failed or did not return status ok."""


class TikTokBlockedError(TikTokClientGetError):
    """Raised when TikTok refuses the request (HTTP 403/429).

    Transient: back off and retry with a fresh session.
    """


class TikTokMissingRehydrationDataError(TikTokScraperError):
    """Raised when request to TikTok did not return any rehydration data."""


class TikTokRehydrationDataAttributeError(TikTokScraperError):
    """Raised when received rehydration data is empty or not valid JSON."""


class TikTokDataExtractionError(TikTokScraperError):
    """Raised when TikTok hydration data structure is unexpected or invalid."""


class TikTokItemUnavailableError(TikTokDataExtractionError):
    """Raised when the page loaded but TikTok reports the item as unavailable.

    TikTok signals this with a non-zero ``statusCode`` in place of the item
    data (e.g. for deleted or private videos). Unlike a block, retrying is
    not expected to help.
    """

    def __init__(self, status_code: int, status_msg: str | None = None) -> None:
        self.status_code = status_code
        self.status_msg = status_msg
        super().__init__(
            f"TikTok reports item as unavailable "
            f"[statusCode: {status_code}; msg: {status_msg}]"
        )
