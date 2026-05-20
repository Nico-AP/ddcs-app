import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

import requests
from django.conf import settings
from django.utils import timezone

from ddcs.metadata.research_api.exceptions import (
    ResearchAPIAccessTokenRetrievalError,
    ResearchAPIRequestError,
)

logger = logging.getLogger("ddcs.metadata.research_api")


class ResearchAPIClient:
    """Client for interacting with TikTok's Research API.

    This client handles authentication, request formatting, and querying
    TikTok's Research API. It automatically manages access token lifecycle,
    including proactive refresh to prevent expiration during long-running operations.

    The client supports querying videos by ID and retrieving user-posted content
    with automatic pagination handling. All requests include comprehensive error
    handling and logging for debugging and monitoring.

    Attributes:
        ACCESS_TOKEN_URL (str): Endpoint for OAuth token retrieval
        VIDEO_QUERY_URL (str): Endpoint for video metadata queries
        USER_QUERY_URL (str): Endpoint for user information queries

    Examples:
        >>> client = ResearchAPIClient()
        >>> videos = client.query_videos(["7123456789", "7987654321"])
        >>> user_content = client.query_user_content(["username1", "username2"])

    Raises:
        AttributeError: If API credentials are not configured in settings
        ResearchAPIAccessTokenRetrievalFailed: If token retrieval fails
        ResearchAPIRequestError: If API requests fail
    """

    ACCESS_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"  # noqa: S105
    VIDEO_QUERY_URL = "https://open.tiktokapis.com/v2/research/video/query/"
    USER_QUERY_URL = "https://open.tiktokapis.com/v2/research/user/info/"

    def __init__(self) -> None:
        self.key = settings.RESEARCH_API_KEY
        self.secret = settings.RESEARCH_API_SECRET

        if self.key is None:
            msg = "The RESEARCH_API_KEY has not been set (in settings.py)"
            raise AttributeError(msg)

        if self.secret is None:
            msg = "The RESEARCH_API_SECRET has not been set (in settings.py)"
            raise AttributeError(msg)

        self.access_token = None
        self.token_expires_at = None
        self._refresh_access_token()

    def _refresh_access_token(self) -> None:
        """Retrieves and stores a new access token from TikTok.

        Updates both the access_token and token_expires_at attributes.
        Tokens typically expire after 2 hours (7200 seconds).
        """
        access_token_url = self.ACCESS_TOKEN_URL

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }

        payload = {
            "client_key": self.key,
            "client_secret": self.secret,
            "grant_type": "client_credentials",
        }

        response = requests.post(
            access_token_url,
            headers=headers,
            data=payload,
            timeout=15,
        )

        if response.status_code != requests.codes.ok:
            e = (
                "Error getting access token for Research API. "
                f"(response status: {response.status_code})"
            )
            logger.error(e)
            raise ResearchAPIAccessTokenRetrievalError(e)

        data = response.json()

        if "error" in data:
            e = f"{data['error']}: {data.get('error_description')}"
            logger.error(e)
            raise ResearchAPIAccessTokenRetrievalError(e)

        self.access_token = data["access_token"]
        expires_in = data.get("expires_in", 7200)  # Default to 2 hours
        self.token_expires_at = timezone.now() + timedelta(seconds=expires_in)

        logger.info("Access token refreshed, expires at %s", self.token_expires_at)

    def _ensure_valid_token(self) -> None:
        """Ensures the access token is valid, refreshing if necessary.

        Checks if the token will expire within the next 5 minutes and
        refreshes it proactively to avoid request failures.
        """
        if (
            self.token_expires_at is None
            or self.token_expires_at <= timezone.now() + timedelta(minutes=5)
        ):
            logger.info("Access token expired or expiring soon, refreshing...")
            self._refresh_access_token()

    def get_access_token(self) -> str:
        """Retrieves the current access token, refreshing if necessary.

        Returns:
            Valid access token
        """
        self._ensure_valid_token()
        return self.access_token

    def query_user_content(self, user_ids: list[str], **kwargs) -> dict[str, Any]:
        """Retrieve videos posted by specific TikTok users via Research API.

        Args:
            user_ids: List of TikTok usernames to query.
            **kwargs: Additional parameters passed to make_query() including:
                start_date, end_date, max_count, cursor, search_id, is_random.

        Returns:
            API response containing retrieved video data and pagination info.

        Raises:
            ResearchAPIRequestError: If the API request fails or returns an error.
        """
        query = {
            "and": [
                {
                    "operation": "IN",
                    "field_name": "username",
                    "field_values": user_ids,
                },
            ],
        }
        return self.make_query(query, **kwargs)

    def query_videos(self, video_ids: list[str], **kwargs) -> dict[str, Any]:
        """Retrieve metadata for specific TikTok videos via Research API.

        Args:
            video_ids: List of TikTok video IDs to query.
            **kwargs: Additional parameters passed to make_query() including:
                start_date, end_date, max_count, cursor, search_id, is_random.

        Returns:
            API response containing video data and pagination info.

        Raises:
            ResearchAPIRequestError: If the API request fails or returns an error.
        """
        query = {
            "and": [
                {
                    "operation": "IN",
                    "field_name": "video_id",
                    "field_values": video_ids,
                },
            ],
        }
        return self.make_query(query, **kwargs)

    def make_query(self, query: dict[str, Any], **kwargs) -> dict[str, Any]:
        """Execute a query against the TikTok Research API.

        Builds the request URL, constructs the query body, and sends the request
        with proper authentication headers. Handles both HTTP and API-level errors.

        Args:
            query: The query structure containing filter conditions.
            **kwargs: Additional query parameters passed to get_query_body().

        Returns:
            The API response data.

        Raises:
            ResearchAPIRequestError: If the HTTP request fails (non-200 status)
                or if the API returns an error response.
        """
        url = self.build_url()
        query_body = self.get_query_body(query, **kwargs)
        response = requests.post(
            url,
            headers=self.get_auth_header(),
            data=json.dumps(query_body),
            timeout=20,
        )

        if response.status_code != requests.codes.ok:
            msg = (
                f"Invalid response from Research API. "
                f"Response status code: {response.status_code} for "
                f"url '{url}' and query body '{json.dumps(query_body)}'",
            )
            raise ResearchAPIRequestError(msg)

        data = response.json()
        if "error" in data and data["error"].get("code") != "ok":
            msg = (
                f"Error in Research API response: "
                f"{data['error'].get('msg')} ({data['error'].get('code')})"
            )
            raise ResearchAPIRequestError(msg)

        return data

    def get_auth_header(self) -> dict[str, str]:
        """Returns the authorization header with a valid access token."""
        self._ensure_valid_token()
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def get_query_body(  # noqa: PLR0913
        self,
        query: dict[str, Any],
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        max_count: int | None = 100,
        cursor: str | None = None,
        search_id: str | None = None,
        is_random: bool | None = False,  # noqa: FBT002
    ) -> dict[str, Any]:
        """Construct the request body for Research API queries.

        Builds the complete query payload including filter conditions, date ranges,
        pagination parameters, and other query options. Handles date formatting
        and provides sensible defaults for optional parameters.

        Args:
            query: Filter conditions (e.g., video IDs, usernames).
            start_date: Query start date. If None, defaults to 30 days before
                end_date (API maximum).
            end_date: Query end date. If None, defaults to today.
            max_count: Maximum results per request (1-100). Default: 100.
            cursor: Pagination cursor for retrieving next page.
            search_id: Search session ID for paginated results.
            is_random: Whether to randomize result order. Default: False.

        Returns:
            Complete request body ready for API submission.

        Note:
            Dates are automatically converted to YYYYMMDD format as required by the API.
            The start_date cannot be more than 30 days before end_date per API limits.
        """
        if end_date is None:
            end_date = timezone.now().date() - timedelta(days=3)
        else:
            end_date = end_date.date()

        if start_date is None:
            start_date = end_date - timedelta(
                days=30,
            )  # Start date can be max. 30 days before end_date.

        if type(start_date) is not date:
            start_date = start_date.date()

        return {
            "query": query,
            "start_date": start_date.isoformat().replace("-", ""),
            "end_date": end_date.isoformat().replace("-", ""),
            "max_count": max_count,
            "cursor": cursor,
            "search_id": search_id,
            "is_random": is_random,
        }

    def build_url(self, query_fields: list[str] | None = None) -> str:
        """Build request URL.

        Includes all available query fields by default (for an overview, see
        https://developers.tiktok.com/doc/research-api-specs-query-videos#query_parameters

        Args:
            query_fields: Query fields to include in response.

        Returns:
            The request URL.
        """
        base_url = self.VIDEO_QUERY_URL

        if query_fields is None:
            query_fields = [
                "id",
                "video_description",
                "create_time",
                "region_code",
                "share_count",
                "view_count",
                "like_count",
                "comment_count",
                "music_id",
                "hashtag_names",
                "username",
                "effect_ids",
                "playlist_id",
                "voice_to_text",
                "is_stem_verified",
                "video_duration",
                "hashtag_info_list",
                "sticker_info_list",
                "effect_info_list",
                "video_mention_list",
                "video_label",
                "video_tag",
            ]

        return base_url + "?fields=" + ",".join(query_fields)
