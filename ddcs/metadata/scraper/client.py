import requests

from ddcs.metadata.scraper.config import (
    BLOCKED_STATUS_CODES,
    DEFAULT_HEADERS,
    MAIN_URL,
    REQUEST_TIMEOUT,
)
from ddcs.metadata.scraper.exceptions import TikTokBlockedError, TikTokClientGetError


class TikTokClient:
    """Handles HTTP requests with proper headers/session management.

    TikTok expects the cookies it hands out on a first visit. They are
    obtained without a browser: the first request of a session is preceded
    by one GET to the TikTok main page, and the session keeps whatever
    cookies that response sets.
    """

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: tuple[float, float] = REQUEST_TIMEOUT,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.timeout = timeout
        self._has_cookies = False

    def get(self, url: str) -> requests.Response:
        """Send GET request to TikTok and return response.

        Args:
            url: The url to get.

        Returns:
            Response from request.

        Raises:
            TikTokBlockedError: If TikTok refused the request.
            TikTokClientGetError: If request failed.
        """
        if not self._has_cookies:
            self._request(MAIN_URL)
            self._has_cookies = True
        return self._request(url)

    def reset_session(self) -> None:
        """Drop the session's cookies; the next request fetches new ones."""
        self.session.cookies.clear()
        self._has_cookies = False

    def _request(self, url: str) -> requests.Response:
        try:
            response = self.session.get(url, timeout=self.timeout)
        except requests.RequestException as e:
            msg = f"Request failed: {e}"
            raise TikTokClientGetError(msg) from e

        if response.status_code in BLOCKED_STATUS_CODES:
            msg = f"Request blocked with status {response.status_code}: {url}"
            raise TikTokBlockedError(msg)
        if not response.ok:
            msg = f"Request failed with status {response.status_code}: {url}"
            raise TikTokClientGetError(msg)

        return response
