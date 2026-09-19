import logging
from typing import Any

import httpx
from django.conf import settings
from django.db import models, transaction

from ddcs.core.types import TikTokUserData
from ddcs.metadata.models import (
    DataOrigins,
    TikTokUser,
    TikTokVideo,
    TikTokVideoClassification,
)

logger = logging.getLogger(__name__)

_TRUNCATION_MARKER = "<...>"
_CLASSIFICATION_CHAR_FIELDS = [
    field
    for field in TikTokVideoClassification._meta.concrete_fields  # noqa: SLF001
    if isinstance(field, models.CharField) and field.max_length
]


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
    REQUEST_TIMEOUT_SECONDS = 15

    def __init__(self) -> None:
        self.token = settings.ZUSE_API_TOKEN
        self.base_url = settings.ZUSE_API_URL
        self.client = httpx.Client(
            timeout=self.REQUEST_TIMEOUT_SECONDS,
            headers={"Authorization": f"Bearer {self.token}"},
        )

    def _get_video(self, video_id: int) -> dict:
        """GET a single video's data. Raises httpx/JSON exceptions on failure."""
        url = f"{self.base_url}/videos/{video_id}"
        response = self.client.get(url)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _fit_char_fields(
        classification: TikTokVideoClassification,
        id_tiktok: Any,  # noqa: ANN401
    ) -> None:
        """Make every ``CharField`` value on ``classification`` fit its column.

        Zuse values are not guaranteed to be short strings: a non-string value
        (e.g. a list) is turned into its ``str()`` by Django on save, so it can
        overflow the column too. A single over-long value would otherwise make
        the whole ``bulk_create`` fail with a ``DataError`` and take the sync
        task (and any backfill chain) down with it, so truncate instead and log
        which video and field were affected.
        """
        for field in _CLASSIFICATION_CHAR_FIELDS:
            value = getattr(classification, field.attname)
            if value is None:
                continue
            text = value if isinstance(value, str) else str(value)
            if len(text) > field.max_length:
                logger.warning(
                    "Truncated %s of video %s from %d to %d characters (%s).",
                    field.name,
                    id_tiktok,
                    len(text),
                    field.max_length,
                    type(value).__name__,
                )
                keep = field.max_length - len(_TRUNCATION_MARKER)
                text = text[:keep] + _TRUNCATION_MARKER
            setattr(classification, field.attname, text)

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
            except ValueError as exc:
                # response.json() failed to decode (e.g. empty/non-JSON body).
                logger.warning("Video %s returned invalid JSON: %s", video_id, exc)
                continue

            if not isinstance(result, dict):
                logger.warning(
                    "Video %s returned unexpected payload type %s; skipping.",
                    video_id,
                    type(result).__name__,
                )
                continue

            results.append(result)

            if len(results) >= self.BATCH_SIZE:
                self._process_results(results)
                results = []

        if results:
            self._process_results(results)

    def _process_results(self, results: list[dict]) -> None:
        id_tiktok_values = []
        for result in results:
            try:
                id_tiktok_values.append(int(result["id_tiktok"]))
            except (KeyError, TypeError, ValueError):
                continue

        video_pk_by_id_tiktok = dict(
            TikTokVideo.objects.filter(id_tiktok__in=id_tiktok_values).values_list(
                "id_tiktok", "id"
            )
        )

        objs_to_create = []

        for result in results:
            try:
                video_pk = video_pk_by_id_tiktok[int(result["id_tiktok"])]
                predictions = result.get("predictions", {})
                sentiments = [
                    e["sentiment"]
                    for e in result.get("entities", [])
                    if e["sentiment"] is not None
                ]

                classification = TikTokVideoClassification(
                    video_id=video_pk,
                    is_political=predictions["is_political"],
                    political_other=predictions["political_other"],
                    political_content=predictions["political_content"],
                    stage1_rationale=predictions["stage1_rationale"] or "",
                    entities=predictions["entities"],
                    keyword_matches=predictions["keyword_matches"],
                    language=predictions["language"] or "",
                    plausible_party=predictions["plausible_party"] or "",
                    classification_ts=predictions["created_at"],
                    # Extracted information
                    is_sentiment_positive="positive" in sentiments,
                    is_sentiment_negative="negative" in sentiments,
                    is_sentiment_neutral="neutral" in sentiments,
                    # Scraped information
                    prediction_scraped=result.get("predictions_div"),
                    media=result.get("media"),
                    scraped_data=result.get("extended"),
                )
                self._fit_char_fields(classification, result["id_tiktok"])
                objs_to_create.append(classification)
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning(
                    "Skipping malformed result %r: %s", result.get("id_tiktok"), exc
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
                    "political_other",
                    "political_content",
                    "stage1_rationale",
                    "entities",
                    "keyword_matches",
                    "language",
                    "plausible_party",
                    "classification_ts",
                    "is_sentiment_positive",
                    "is_sentiment_negative",
                    "is_sentiment_neutral",
                    "prediction_scraped",
                    "media",
                    "scraped_data",
                ],
            )
