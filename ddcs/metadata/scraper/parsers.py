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

# Blocks of a WebVTT file that are not cues.
_WEBVTT_NON_CUE_BLOCKS = ("WEBVTT", "NOTE", "STYLE", "REGION")
# Inline markup inside cue text, e.g. <c.yellow>, <v Speaker>, <00:00:01.000>.
_WEBVTT_TAG_RE = re.compile(r"<[^>]*>")

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

    @staticmethod
    def select_original_caption(video_data: dict[str, Any]) -> dict[str, Any] | None:
        """Pick the original-language caption from scraped video data.

        TikTok lists a video's captions under ``video.claInfo.captionInfos``.
        Besides the transcript in the language spoken in the video there
        may be machine translations; only the entry flagged
        ``isOriginalCaption`` is of interest. Captions in a format other
        than WebVTT are ignored.

        Args:
            video_data: Video data as returned by ``extract_video_data``.

        Returns:
            The caption entry (with ``url``, ``language``, ``isAutoGen``, ...)
            or None if the video has no original-language WebVTT caption.
        """
        file_data = video_data.get("video") or {}
        caption_infos = (file_data.get("claInfo") or {}).get("captionInfos") or []
        for caption in caption_infos:
            if (
                isinstance(caption, dict)
                and caption.get("isOriginalCaption")
                and caption.get("captionFormat") == "webvtt"
                and caption.get("url")
            ):
                return caption
        return None

    @staticmethod
    def webvtt_to_text(vtt: str) -> str:
        """Reduce a WebVTT caption file to its spoken text.

        Drops the header, cue identifiers, timestamps and inline markup and
        joins what is left with single spaces, which is the shape of the
        Research API's ``voice_to_text``.

        Args:
            vtt: Content of a WebVTT file.

        Returns:
            The cue texts as one line of plain text.
        """
        texts = []
        blocks = re.split(r"\n\s*\n", vtt.replace("\r\n", "\n").replace("\r", "\n"))
        for block in blocks:
            lines = [line.strip() for line in block.strip().split("\n")]
            if lines[0].startswith(_WEBVTT_NON_CUE_BLOCKS):
                continue
            # A cue is an optional identifier line, the timing line, then text.
            timing = next((i for i, line in enumerate(lines) if "-->" in line), None)
            if timing is None:
                continue
            texts.extend(_WEBVTT_TAG_RE.sub("", line) for line in lines[timing + 1 :])
        return " ".join(" ".join(texts).split())
