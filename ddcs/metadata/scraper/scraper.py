import time
from collections.abc import Callable, Generator
from typing import Any, TypedDict

from ddcs.metadata.scraper.client import TikTokClient
from ddcs.metadata.scraper.config import BASE_URLS, RATE_LIMIT_DELAY
from ddcs.metadata.scraper.exceptions import TikTokBlockedError, TikTokScraperError
from ddcs.metadata.scraper.parsers import TikTokParser


class VideoScrapingSuccess(TypedDict):
    success: bool  # Always True
    data: dict[str, Any]
    video_id: str


class VideoScrapingError(TypedDict):
    success: bool  # Always False
    error: str
    error_type: str  # Name of the TikTokScraperError subclass
    exception: TikTokScraperError
    video_id: str


class UserScrapingSuccess(TypedDict):
    success: bool  # Always True
    data: dict[str, Any]
    username: str


class UserScrapingError(TypedDict):
    success: bool  # Always False
    error: str
    error_type: str  # Name of the TikTokScraperError subclass
    exception: TikTokScraperError
    username: str


class ScrapedCaption(TypedDict):
    language: str  # TikTok's language tag, e.g. "deu-DE"
    is_auto_generated: bool | None
    vtt: str  # The WebVTT file as downloaded


VideoScrapingResult = VideoScrapingSuccess | VideoScrapingError
UserScrapingResult = UserScrapingSuccess | UserScrapingError


class TikTokScraper:
    """Scraper for extracting TikTok video metadata from tiktok.com.

    This scraper orchestrates the video metadata extraction from TikTok
    by coordinating HTTP requests, HTML parsing, and data extraction.
    It handles both single video and batch processing with built-in rate limiting
    and error handling.

    Attributes:
        client (TikTokClient): HTTP client for making requests to TikTok
        parser (TikTokParser): Parser class for extracting data from responses
        rate_delay (float): Delay in seconds between requests for rate limiting

    Examples:
        >>> scraper = TikTokScraper(rate_delay=1.0)
        >>>
        >>> # Process videos with error handling
        >>> for result in scraper.scrape_video_list(["123", "456"]):
        ...     if result["success"]:
        ...         process_video(result["data"])
        ...     else:
        ...         print(f"Failed {result['video_id']}: {result['error']}")
    """

    def __init__(
        self,
        rate_delay: float = RATE_LIMIT_DELAY,
        client: TikTokClient | None = None,
    ) -> None:
        self.client = client or TikTokClient()
        self.parser = TikTokParser
        self.rate_delay = rate_delay

    def scrape_video_list(
        self,
        video_ids: list[str],
    ) -> Generator[VideoScrapingResult, None, None]:
        """Generator that yields video scraping results with error handling.

        Args:
            video_ids: List of video IDs to scrape.

        Yields:
            Either success with data or error with message.

        Examples:
            >>> for result in scraper.scrape_video_list(["123", "456"]):
            ...     if result["success"]:
            ...         process_video(result["data"])
            ...     else:
            ...         print(f"Failed {result['video_id']}: {result['error']}")
        """
        yield from self._scrape_list(video_ids, self.scrape_video, "video_id")

    def scrape_video(self, video_id: str) -> dict[str, Any]:
        """Scrape a single video.

        Args:
            video_id: ID of the video to scrape.

        Returns:
            The extracted video data.

        Raises:
            TikTokClientGetError: Raised when GET request to TikTok did not
                return status ok.
            TikTokMissingRehydrationDataError: When rehydration data script
                not found in response text.
            TikTokRehydrationDataAttributeError: When rehydration data is
                empty or not valid JSON.
            TikTokDataExtractionError: When TikTok hydration data structure is
                unexpected or invalid.
        """
        url = self.get_video_url(video_id)
        response = self.client.get(url)
        rehydration_data = self.parser.load_rehydration_data(response.text)
        return self.parser.extract_video_data(rehydration_data)

    def fetch_original_caption(
        self, video_data: dict[str, Any]
    ) -> ScrapedCaption | None:
        """Download the original-language caption of a scraped video.

        The caption is a separate file that the video data only links to.
        The link is signed and expires within days, so this has to happen
        right after the video was scraped. Costs one extra request, which
        is preceded by the usual rate-limit delay.

        Args:
            video_data: Video data as returned by ``scrape_video``.

        Returns:
            The caption, or None if the video has no original-language caption
            (no request is made in that case).

        Raises:
            TikTokClientGetError: Raised when the caption could not be
                downloaded.
        """
        caption = self.parser.select_original_caption(video_data)
        if caption is None:
            return None

        if self.rate_delay:
            time.sleep(self.rate_delay)
        response = self.client.get(caption["url"])
        return ScrapedCaption(
            language=caption.get("language") or "",
            is_auto_generated=caption.get("isAutoGen"),
            vtt=response.text,
        )

    def scrape_user_list(
        self,
        usernames: list[str],
    ) -> Generator[UserScrapingResult, None, None]:
        """Generator that yields user scraping results with error handling.

        Args:
            usernames: List of usernames to scrape.

        Yields:
            Either success with data or error with message.

        Examples:
            >>> for result in scraper.scrape_user_list(["namea", "nameB"]):
            ...     if result["success"]:
            ...         # do something
            ...         pass
            ...     else:
            ...         print(f"Failed {result['username']}: {result['error']}")
        """
        yield from self._scrape_list(usernames, self.scrape_user, "username")

    def scrape_user(self, username: str) -> dict[str, Any]:
        """Scrape a single user.

        Args:
            username: Unique username of the user to scrape.

        Returns:
            The extracted user data.

        Raises:
            TikTokClientGetError: Raised when GET request to TikTok did not
                return status ok.
            TikTokMissingRehydrationDataError: When rehydration data script
                not found in response text.
            TikTokRehydrationDataAttributeError: When rehydration data is
                empty or not valid JSON.
            TikTokDataExtractionError: When TikTok hydration data structure is
                unexpected or invalid.
        """
        url = self.get_user_url(username)
        response = self.client.get(url)
        rehydration_data = self.parser.load_rehydration_data(response.text)
        return self.parser.extract_user_data(rehydration_data)

    def _scrape_list(
        self,
        identifiers: list[str],
        scrape_one: Callable[[str], dict[str, Any]],
        identifier_key: str,
    ) -> Generator[dict[str, Any], None, None]:
        for i, identifier in enumerate(identifiers):
            if self.rate_delay and i > 0:
                time.sleep(self.rate_delay)

            try:
                data = self._scrape_with_fresh_session_on_block(scrape_one, identifier)
            except TikTokScraperError as e:
                yield {
                    "success": False,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "exception": e,
                    identifier_key: identifier,
                }
            else:
                yield {"success": True, "data": data, identifier_key: identifier}

    def _scrape_with_fresh_session_on_block(
        self,
        scrape_one: Callable[[str], dict[str, Any]],
        identifier: str,
    ) -> dict[str, Any]:
        """Scrape one item; if blocked, retry once with new cookies."""
        try:
            return scrape_one(identifier)
        except TikTokBlockedError:
            self.client.reset_session()
            if self.rate_delay:
                time.sleep(self.rate_delay)
            return scrape_one(identifier)

    @staticmethod
    def get_video_url(video_id: str) -> str:
        """Construct video url.

        Args:
            video_id: Video id.

        Returns:
            The generic url pointing to the video.
        """
        return BASE_URLS["video"].replace("{id}", str(video_id))

    @staticmethod
    def get_user_url(user_id: str) -> str:
        """Construct user url.

        Args:
            user_id: UserVideo id.

        Returns:
            The generic url pointing to the user page.
        """
        return BASE_URLS["user"].replace("{username}", str(user_id))
