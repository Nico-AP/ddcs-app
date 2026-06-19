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
        # Query Research API
        for data in self.client.query_videos_by_username(usernames, **kwargs):
            self._process_api_response(data)
            self.sync_stats["videos_retrieved"] += 1

        logger.info(
            "Query Videos by username; Usernames: %s; Retrieved %s videos",
            usernames,
            self.sync_stats["videos_retrieved"],
        )

    def get_hashtag_videos(self, hashtags: list[str], **kwargs) -> None:
        """Retrieve videos associated with specific hashtags via Research API.

        Queries the Research API for videos associated with the provided hashtags,
        processes the results, and stores them in the database.

        Args:
            hashtags (list[str]): List of hashtags to retrieve videos for.
            **kwargs: Additional parameters to pass to the API client
                (cursor, search_id, etc.).

        Returns:
            None
        """
        # Query Research API
        for data in self.client.query_videos_by_hashtag(hashtags, **kwargs):
            self._process_api_response(data)
            self.sync_stats["videos_retrieved"] += 1

        logger.info(
            "Query Videos by hashtag; Hashtags: %s; Retrieved %s videos",
            hashtags,
            self.sync_stats["videos_retrieved"],
        )

    def _process_api_response(self, data: dict) -> None:
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
