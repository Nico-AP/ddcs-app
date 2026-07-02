import logging
from datetime import UTC, datetime
from typing import Any

from django.conf import settings
from tiktok_metadata_kit.research_api import ResearchAPIClient

from ddcs.metadata.models import (
    DataOrigins,
    TikTokHashtag,
    TikTokMusic,
    TikTokUser,
    TikTokVideo,
)
from ddcs.metadata.research_api.models import (
    APIHashtagInfos,
    APIVideoInfos,
    APIVideoStatistics,
)
from ddcs.metadata.utils import infer_publication_date_from_id

logger = logging.getLogger(__name__)


class ResearchAPIService:
    """Service for retrieving TikTok video metadata via the Research API.

    This service interfaces with TikTok's Research API to retrieve official
    video metadata and statistics. It handles data retrievel and mapping.

    The service provides two main data retrieval methods:
    1. get_user_videos() - Retrieves videos posted by specific users
    2. get_hashtag_videos() - Retrieves videos associated with specific hashtags

    Attributes:
        client (ResearchAPIClient): Instance for making Research API requests.

    Examples:
        >>> service = ResearchAPIService()
        >>> service.get_user_videos(['username1', 'username2'])
        >>> service.get_hashtag_videos(['tag1', 'tag2'])
    """

    def __init__(self) -> None:
        self.client = ResearchAPIClient(
            api_key=settings.TIKTOK_RESEARCH_API_KEY,
            api_secret=settings.TIKTOK_RESEARCH_API_SECRET,
        )

        # Track how many objects are created
        self.sync_stats = {
            "users_created": 0,
            "videos_created": 0,
            "hashtags_created": 0,
            "music_created": 0,
            "videos_retrieved": 0,
            "pages_retrieved": 0,
        }

    def get_user_videos(self, usernames: list[str], **kwargs) -> None:
        """Retrieve videos posted by specific TikTok users via Research API.

        Queries the Research API for videos posted by the provided usernames,
        processes the results, and stores them in the database.

        Args:
            usernames (list[str]): List of TikTok usernames to retrieve videos for.
            **kwargs: Additional parameters to pass to the API client
                (cursor, search_id, etc.).

        Returns:
            None
        """

        query = {
            "and": [
                {
                    "operation": "IN",
                    "field_name": "username",
                    "field_values": usernames,
                }
            ]
        }
        videos_retrieved, pages_retrieved = self._query_videos_pages(query, **kwargs)

        logger.info(
            "Query Videos by username; Usernames: %s; Retrieved %s videos on %s pages",
            usernames,
            videos_retrieved,
            pages_retrieved,
        )

    def get_videos_by_keywords(self, keywords: list[str], **kwargs) -> None:

        query = {
            "and": [
                {
                    "operation": "IN",
                    "field_name": "keyword",
                    "field_values": keywords,
                }
            ]
        }

        videos_retrieved, pages_retrieved = self._query_videos_pages(query, **kwargs)

        logger.info(
            "Query Videos by keyword; Keywords: %s; Retrieved %s videos on %s pages",
            keywords,
            videos_retrieved,
            pages_retrieved,
        )

    def _query_videos_pages(self, query: dict[str, Any], **kwargs) -> tuple[int, int]:
        videos_retrieved = 0
        pages_retrieved = 0
        for page in self.client.query_videos_pages(query, **kwargs):
            pages_retrieved += 1
            self.sync_stats["pages_retrieved"] += 1
            for video in page.get("data", {}).get("videos", []):
                self._process_api_response(video)
                videos_retrieved += 1
                self.sync_stats["videos_retrieved"] += 1

        return videos_retrieved, pages_retrieved

    def _process_api_response(self, data: dict) -> None:
        data = self._sanitize(data)
        user = self._sync_user(data["username"])
        music = self._sync_music(data.get("music_id"))
        video = self._sync_video(data, user=user, music=music)
        self._sync_video_statistics(data, video=video)
        self._sync_hashtags(data.get("hashtag_info_list", []), video=video)

    def _sync_user(self, username: str) -> TikTokUser:
        user, created = TikTokUser.objects.get_or_create(
            name=username,
            defaults={"added_by": DataOrigins.RESEARCH_API},
        )
        if created:
            self.sync_stats["users_created"] += 1
        return user

    def _sync_music(self, music_id: int | None) -> TikTokMusic | None:
        if not music_id:
            return None
        music, created = TikTokMusic.objects.get_or_create(
            id_tiktok=music_id,
            defaults={"added_by": DataOrigins.RESEARCH_API},
        )
        if created:
            self.sync_stats["music_created"] += 1
        return music

    def _sync_video(
        self, video_data: dict[str, Any], user: TikTokUser, music: TikTokMusic | None
    ) -> TikTokVideo:
        video, created = TikTokVideo.objects.get_or_create(
            id_tiktok=video_data["id"],
            defaults={
                "added_by": DataOrigins.RESEARCH_API,
                "user": user,
                "music": music,
                "inferred_create_time": infer_publication_date_from_id(
                    video_data["id"]
                ),
            },
        )
        if created:
            self.sync_stats["videos_created"] += 1

        if not video.api_infos.exists():
            video_infos = self._clean_video(video_data)
            APIVideoInfos.objects.create(video=video, **video_infos)
        return video

    def _sync_video_statistics(self, data: dict[str, Any], video: TikTokVideo) -> None:
        clean_data = self._clean_video_statistics(data)
        APIVideoStatistics.objects.create(video=video, **clean_data)

    def _sync_hashtags(self, hashtag_data: list[dict], video: TikTokVideo) -> None:
        hashtags = [self._sync_hashtag(h) for h in hashtag_data]
        if hashtags:
            # TODO: Decide on behaviour here; overwrite existing hashtags?
            #  Accessed by both scraper and api
            video.hashtags.set(hashtags)

    def _sync_hashtag(self, hashtag_data: dict[str, Any]) -> TikTokHashtag:
        clean_data = self._clean_hashtag(hashtag_data)
        hashtag, created = TikTokHashtag.objects.get_or_create(
            name=hashtag_data["hashtag_name"],
            defaults={
                "id_tiktok": hashtag_data["hashtag_id"],
                "added_by": DataOrigins.RESEARCH_API,
            },
        )
        if created:
            self.sync_stats["hashtags_created"] += 1

        if not created and hashtag.id_tiktok is None:
            hashtag.id_tiktok = hashtag_data["hashtag_id"]
            hashtag.save(update_fields=["id_tiktok"])

        if not hashtag.api_infos.exists():
            APIHashtagInfos.objects.create(hashtag=hashtag, **clean_data)

        return hashtag

    @staticmethod
    def _clean_video(api_data: dict[str, Any]) -> dict[str, Any]:
        """Map api response to APIVideoInfos."""

        create_time_raw = api_data.get("create_time")
        if create_time_raw:
            create_time = datetime.fromtimestamp(api_data["create_time"], tz=UTC)
        else:
            create_time = None

        return {
            "description": api_data.get("video_description", ""),
            "create_time": create_time,
            "region_code": api_data.get("region_code", ""),
            "duration": api_data.get("video_duration"),
            "voice_to_text": api_data.get("voice_to_text", ""),
            "is_stem_verified": api_data.get("is_stem_verified"),
            "video_mention_list": api_data.get("video_mention_list"),
            "video_label": api_data.get("video_label"),
            "effect_list": api_data.get("effect_info_list"),
        }

    @staticmethod
    def _clean_video_statistics(api_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "view_count": api_data.get("view_count"),
            "like_count": api_data.get("like_count"),
            "comment_count": api_data.get("comment_count"),
            "share_count": api_data.get("share_count"),
            "favorites_count": api_data.get("favorites_count"),
        }

    @staticmethod
    def _clean_hashtag(api_data: dict[str, Any]) -> dict[str, Any]:
        """Map api response to APIHashtagInfos."""
        return {
            "description": api_data.get("hashtag_description", ""),
        }

    @staticmethod
    def _sanitize(value: Any) -> Any:  # noqa: ANN401
        """Recursively strip NUL bytes from strings anywhere in the API payload."""
        if isinstance(value, str):
            return value.replace("\x00", "")
        if isinstance(value, dict):
            return {k: ResearchAPIService._sanitize(v) for k, v in value.items()}
        if isinstance(value, list):
            return [ResearchAPIService._sanitize(v) for v in value]
        return value
