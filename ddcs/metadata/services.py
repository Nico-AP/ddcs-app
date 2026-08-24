import logging

import httpx
from django.conf import settings
from django.db import transaction

from ddcs.core.types import TikTokUserData
from ddcs.metadata.models import (
    DataOrigins,
    TikTokUser,
    TikTokVideo,
    TikTokVideoClassification,
)

logger = logging.getLogger(__name__)


# TODO: When scraper is introduced, add a specific scrape priority to the
#  entries created here.
# TODO: Make this task async/convert to celery task.
def register_donation_metadata(data: TikTokUserData) -> None:
    """Creates DB entries based on donation data.

    Handles watch history, followed accounts, and liked videos.
    """
    # Watch history
    if data.watch_history:
        videos_to_add = [
            TikTokVideo(id_tiktok=record["video_id"], added_by=DataOrigins.DONATION)
            for record in data.watch_history
        ]
        TikTokVideo.objects.bulk_create(videos_to_add, ignore_conflicts=True)

    # Liked videos
    if data.liked_videos:
        videos_to_add = [
            TikTokVideo(id_tiktok=record["video_id"], added_by=DataOrigins.DONATION)
            for record in data.liked_videos
        ]
        TikTokVideo.objects.bulk_create(videos_to_add, ignore_conflicts=True)

    # Followed accounts
    if data.followed_accounts:
        user_names = {record.get("username") for record in data.followed_accounts} - {
            None
        }
        users_to_add = [
            TikTokUser(name=user_name, added_by=DataOrigins.DONATION)
            for user_name in user_names
        ]
        TikTokUser.objects.bulk_create(users_to_add, ignore_conflicts=True)


# Service to sync with Zuse


class ZuseAPIClient:
    BATCH_SIZE = 100

    def __init__(self) -> None:
        self.token = settings.ZUSE_API_TOKEN
        self.base_url = settings.ZUSE_API_URL
        self.client = httpx.Client(
            timeout=15,
            headers={"Authorization": f"Bearer {self.token}"},
        )

    def _get_video(self, video_id: int) -> httpx.Response:
        """GET a single video's data. Raises httpx exceptions on failure."""
        url = f"{self.base_url}/videos/{video_id}"
        response = self.client.get(url)
        response.raise_for_status()
        return response.json()

    def sync_videos(self, video_ids: list[int]) -> None:
        results = []
        for video_id in video_ids:
            try:
                result = self._get_video(video_id)
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "Video %s request failed: %s %s",
                    video_id,
                    exc.response.status_code,
                    exc.response.text,
                )
                continue
            except httpx.RequestError as exc:
                logger.warning(
                    "Video %s request errored: %s %s — %s",
                    video_id,
                    exc.request.method,
                    exc.request.url,
                    exc,
                )
                continue

            results.append(result)

            if len(results) >= self.BATCH_SIZE:
                self._process_results(results)
                results = []

        if results:
            self._process_results(results)

    def _process_results(self, results: list[dict]) -> None:

        objs_to_create = []

        for result in results:
            try:
                predictions = result.get("predictions", {})
                sentiments = [
                    e["sentiment"]
                    for e in result.get("entities", [])
                    if e["sentiment"] is not None
                ]

                objs_to_create.append(
                    TikTokVideoClassification(
                        video_id=int(result["video_id"]),
                        is_political=predictions["is_political"],
                        stage1_rationale=predictions["stage1_rationale"],
                        entities=predictions["entities"],
                        keyword_matches=predictions["keyword_matches"],
                        scraped_data=result["extended"],
                        video_path=result["video_path"],
                        image_paths=result["image_paths"],
                        post_scrape_prediction=result.get("predictions_div"),
                        is_sentiment_positive="positive" in sentiments,
                        is_sentiment_negative="negative" in sentiments,
                        is_sentiment_neutral="neutral" in sentiments,
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning(
                    "Skipping malformed result %r: %s", result.get("video_id"), exc
                )
                continue

        if not objs_to_create:
            return

        with transaction.atomic():
            TikTokVideoClassification.objects.bulk_create(
                objs_to_create,
                update_conflicts=True,
                unique_fields=["video"],
                update_fields=[
                    "is_political",
                    "stage1_rationale",
                    "entities",
                    "keyword_matches",
                    "scraped_data",
                    "video_path",
                    "image_paths",
                    "post_scrape_prediction",
                    "is_sentiment_positive",
                    "is_sentiment_negative",
                    "is_sentiment_neutral",
                ],
            )
