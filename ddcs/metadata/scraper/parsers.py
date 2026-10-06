import json
import re
from typing import Any

from ddcs.metadata.scraper.exceptions import (
    TikTokDataExtractionError,
    TikTokItemUnavailableError,
    TikTokMissingRehydrationDataError,
    TikTokRehydrationDataAttributeError,
)

_REHYDRATION_SCRIPT_RE = re.compile(
    r'<script[^>]*\bid="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
    re.DOTALL,
)

_VIDEO_DATA_PATH = (
    "__DEFAULT_SCOPE__",
    "webapp.video-detail",
    "itemInfo",
    "itemStruct",
)
_USER_DATA_PATH = (
    "__DEFAULT_SCOPE__",
    "webapp.user-detail",
    "userInfo",
)


class TikTokParser:
    """Handles parsing of HTML/JSON data received from TikTok."""

    @staticmethod
    def load_rehydration_data(response_text: str) -> dict:
        """Extract the rehydration data from the response text.

        Args:
            response_text: Content of a requests.Response object.

        Returns:
            The extracted rehydration data as a dictionary.

        Raises:
            TikTokMissingRehydrationDataError: When rehydration data script
                not found in response text.
            TikTokRehydrationDataAttributeError: When rehydration data script
                is empty or does not contain valid JSON.
        """
        match = _REHYDRATION_SCRIPT_RE.search(response_text)
        if not match:
            msg = "Rehydration data script not found in response."
            raise TikTokMissingRehydrationDataError(msg)

        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError as e:
            msg = f"Rehydration data script does not contain valid JSON: {e}"
            raise TikTokRehydrationDataAttributeError(msg) from e

    @staticmethod
    def extract_video_data(json_data: dict) -> dict[str, Any]:
        """Extract the video data from the JSON response.

        Returns all the data found under the path:
        `__DEFAULT_SCOPE__.webapp.video-detail.itemInfo.itemStruct`

        Args:
            json_data: JSON response from TikTok.

        Returns:
            The extracted video data as a dictionary.

        Raises:
            TikTokItemUnavailableError: When TikTok reports a non-zero
                statusCode instead of the video data.
            TikTokDataExtractionError: When json_data does not contain expected keys.
        """
        return TikTokParser._walk(json_data, _VIDEO_DATA_PATH)

    @staticmethod
    def extract_user_data(json_data: dict) -> dict[str, Any]:
        """Extract the user data from the JSON response.

        Returns all the data found under the path:
        `__DEFAULT_SCOPE__.webapp.user-detail.userInfo`

        Args:
            json_data: JSON response from TikTok.

        Returns:
            The extracted user data as a dictionary.

        Raises:
            TikTokItemUnavailableError: When TikTok reports a non-zero
                statusCode instead of the user data.
            TikTokDataExtractionError: When json_data does not contain expected keys.
        """
        return TikTokParser._walk(json_data, _USER_DATA_PATH)

    @staticmethod
    def _walk(json_data: Any, path: tuple[str, ...]) -> Any:  # noqa: ANN401
        for key in path:
            if isinstance(json_data, dict) and key in json_data:
                json_data = json_data[key]
                continue

            # Where the data is missing, TikTok leaves a status in its place.
            status_code = (
                json_data.get("statusCode") if isinstance(json_data, dict) else None
            )
            if status_code:
                raise TikTokItemUnavailableError(
                    status_code, json_data.get("statusMsg")
                )
            msg = f"Could not find key '{key}' in json_data"
            raise TikTokDataExtractionError(msg)

        return json_data
