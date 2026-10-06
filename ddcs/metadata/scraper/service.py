"""Persistence and queueing for scraped TikTok data.

This module is the single ingestion path for scraped data: nothing else
should create ``ScrapeTarget`` / ``*Scraped`` rows, so that queue state and
the "don't overwrite Research API data" policy stay consistent.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from itertools import batched
from typing import TYPE_CHECKING, Any, TypedDict

from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from ddcs.metadata.models import (
    DataOrigins,
    TikTokHashtag,
    TikTokMusic,
    TikTokUser,
    TikTokVideo,
)
from ddcs.metadata.research_api.models import APIVideoInfos
from ddcs.metadata.scraper.exceptions import (
    TikTokBlockedError,
    TikTokItemUnavailableError,
    TikTokScraperError,
)
from ddcs.metadata.scraper.models import (
    ScrapeTarget,
    VideoInfosScraped,
    VideoStatisticsScraped,
)
from ddcs.metadata.scraper.parsers import TikTokParser
from ddcs.metadata.scraper.scraper import TikTokScraper
from ddcs.metadata.scraper.utils import int_or_none
from ddcs.metadata.utils import infer_publication_date_from_id

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

_ENQUEUE_CHUNK_SIZE = 500

# Keys dropped from the stored raw payload: large encoding details that are
# of no analytical use. URL values (signed, short-lived) are dropped too.
_RAW_EXCLUDED_KEYS = frozenset({"bitrateInfo", "PlayAddrStruct"})


def _without_api_infos(video_pks: Iterable[int]) -> dict[int, int]:
    """Of the given videos, those lacking Research API infos: pk -> TikTok ID."""
    return dict(
        TikTokVideo.objects.filter(pk__in=video_pks)
        .exclude(Exists(APIVideoInfos.objects.filter(video=OuterRef("pk"))))
        .values_list("pk", "id_tiktok")
    )


def enqueue_video_pks(video_pks: Iterable[int]) -> int:
    """Queue the given videos (by primary key) for scraping.

    Videos that already have Research API infos are skipped, and videos
    that are already queued are left as they are. Each new target records
    the publish time encoded in the video's TikTok ID, which is what the
    queue is ordered by (newest first): videos disappear over time, so the
    recent ones are the ones still worth catching.

    Returns the number of newly created targets.
    """
    created = 0
    for chunk in batched(set(video_pks), _ENQUEUE_CHUNK_SIZE):
        candidates = _without_api_infos(chunk)
        queued = set(
            ScrapeTarget.objects.filter(video_id__in=candidates).values_list(
                "video_id", flat=True
            )
        )
        new = [
            ScrapeTarget(
                video_id=pk,
                inferred_create_time=infer_publication_date_from_id(id_tiktok),
            )
            for pk, id_tiktok in candidates.items()
            if pk not in queued
        ]
        ScrapeTarget.objects.bulk_create(new, ignore_conflicts=True)
        created += len(new)
    return created


def enqueue_videos(id_tiktoks: Iterable[int]) -> int:
    """Queue the videos with the given TikTok IDs for scraping.

    IDs without a ``TikTokVideo`` row are ignored. See
    :func:`enqueue_video_pks` for the rules.
    """
    created = 0
    for chunk in batched(set(id_tiktoks), _ENQUEUE_CHUNK_SIZE):
        video_pks = TikTokVideo.objects.filter(id_tiktok__in=chunk).values_list(
            "pk", flat=True
        )
        created += enqueue_video_pks(video_pks)
    return created


class ScrapeBatchStats(TypedDict):
    scraped: int
    unavailable: int
    failed: int
    blocked: int
    covered_by_api: int
    captions_fetched: int
    # Videos that have a caption which could not be downloaded. The videos
    # themselves still count as scraped.
    captions_failed: int
    # True if the batch stopped early because TikTok kept blocking us.
    aborted: bool


class ScraperService:
    """Works off the ``ScrapeTarget`` queue and stores what was scraped."""

    # After this many blocked videos in a row the batch is abandoned:
    # continuing would only burn through the queue.
    CONSECUTIVE_BLOCKS_BEFORE_ABORT = 3
    # A failed target is not retried before this much time has passed.
    FAILED_RETRY_BACKOFF = timedelta(hours=6)

    def __init__(
        self,
        scraper: TikTokScraper | None = None,
        max_attempts: int | None = None,
        fetch_captions: bool | None = None,
    ) -> None:
        self.scraper = scraper or TikTokScraper(
            rate_delay=settings.TIKTOK_SCRAPER_RATE_DELAY
        )
        self.max_attempts = max_attempts or settings.TIKTOK_SCRAPER_MAX_ATTEMPTS
        self.fetch_captions = (
            settings.TIKTOK_SCRAPER_FETCH_CAPTIONS
            if fetch_captions is None
            else fetch_captions
        )

    def scrape_batch(
        self,
        limit: int,
        deadline: float | None = None,
    ) -> ScrapeBatchStats:
        """Scrape up to ``limit`` queued videos, newest publish time first.

        Args:
            limit: Maximum number of targets to work on.
            deadline: ``time.monotonic()`` value after which no further
                video is started. ``None`` means no time limit.
        """
        stats: ScrapeBatchStats = {
            "scraped": 0,
            "unavailable": 0,
            "failed": 0,
            "blocked": 0,
            "covered_by_api": 0,
            "captions_fetched": 0,
            "captions_failed": 0,
            "aborted": False,
        }
        targets = self._select_targets(limit, stats)
        results = self.scraper.scrape_video_list(
            [str(target.video.id_tiktok) for target in targets]
        )

        consecutive_blocks = 0
        for target in targets:
            if deadline is not None and time.monotonic() > deadline:
                break
            result = next(results)

            if result["success"]:
                consecutive_blocks = 0
                caption = self._fetch_caption(target, result["data"], stats)
                self._handle_success(target, result["data"], caption, stats)
                continue

            error = result["exception"]
            if isinstance(error, TikTokBlockedError):
                # Says nothing about the video: leave the target untouched.
                stats["blocked"] += 1
                consecutive_blocks += 1
                if consecutive_blocks >= self.CONSECUTIVE_BLOCKS_BEFORE_ABORT:
                    stats["aborted"] = True
                    break
                continue

            consecutive_blocks = 0
            if isinstance(error, TikTokItemUnavailableError):
                self._mark(
                    target,
                    ScrapeTarget.Status.UNAVAILABLE,
                    error,
                    tiktok_status_code=int_or_none(error.status_code),
                )
                stats["unavailable"] += 1
            else:
                self._mark(target, ScrapeTarget.Status.FAILED, error)
                stats["failed"] += 1

        return stats

    def _select_targets(
        self, limit: int, stats: ScrapeBatchStats
    ) -> list[ScrapeTarget]:
        retry_before = timezone.now() - self.FAILED_RETRY_BACKOFF
        targets = list(
            ScrapeTarget.objects.filter(
                Q(status=ScrapeTarget.Status.PENDING)
                | Q(
                    status=ScrapeTarget.Status.FAILED,
                    attempts__lt=self.max_attempts,
                    last_attempted_at__lt=retry_before,
                )
            )
            .select_related("video")
            .order_by("-inferred_create_time", "id")[:limit]
        )

        # The Research API may have delivered some of them since they were
        # queued; those no longer need scraping.
        uncovered: list[ScrapeTarget] = []
        for chunk in batched(targets, _ENQUEUE_CHUNK_SIZE):
            still_missing = set(_without_api_infos(t.video_id for t in chunk))
            covered = [t.pk for t in chunk if t.video_id not in still_missing]
            if covered:
                ScrapeTarget.objects.filter(pk__in=covered).update(
                    status=ScrapeTarget.Status.COVERED_BY_API,
                    updated_at=timezone.now(),
                )
                stats["covered_by_api"] += len(covered)
            uncovered.extend(t for t in chunk if t.video_id in still_missing)
        return uncovered

    def _fetch_caption(
        self, target: ScrapeTarget, data: dict[str, Any], stats: ScrapeBatchStats
    ) -> dict[str, Any]:
        """Get the video's original-language caption as ``VideoInfosScraped`` fields.

        Never raises for a caption problem: the video data is worth storing
        without it, so a failed download is only recorded in
        ``caption_status``.
        """
        status = VideoInfosScraped.CaptionStatus
        if not self.fetch_captions:
            return {"caption_status": status.NOT_REQUESTED}

        try:
            caption = self.scraper.fetch_original_caption(data)
        except TikTokScraperError as e:
            logger.warning(
                "Could not fetch caption for video %s: %s", target.video.id_tiktok, e
            )
            stats["captions_failed"] += 1
            return {"caption_status": status.FAILED}

        if caption is None:
            return {"caption_status": status.NONE_AVAILABLE}

        stats["captions_fetched"] += 1
        return {
            "caption_status": status.FETCHED,
            "voice_to_text": TikTokParser.webvtt_to_text(caption["vtt"]),
            "caption_vtt": caption["vtt"],
            "caption_language": caption["language"],
            "caption_is_auto_generated": caption["is_auto_generated"],
        }

    def _handle_success(
        self,
        target: ScrapeTarget,
        data: dict[str, Any],
        caption: dict[str, Any],
        stats: ScrapeBatchStats,
    ) -> None:
        try:
            self._store(target, data, caption)
        except SoftTimeLimitExceeded:
            raise
        except Exception as e:
            # TikTok delivered something we could not map or store. Don't
            # let one odd payload stop the batch.
            logger.exception(
                "Could not store scraped data for video %s.", target.video.id_tiktok
            )
            self._mark(target, ScrapeTarget.Status.FAILED, e)
            stats["failed"] += 1
        else:
            stats["scraped"] += 1

    @transaction.atomic
    def _store(
        self, target: ScrapeTarget, data: dict[str, Any], caption: dict[str, Any]
    ) -> None:
        video = target.video
        VideoInfosScraped.objects.create(
            video=video, **self._clean_video(data), **caption
        )
        VideoStatisticsScraped.objects.create(
            video=video, **self._clean_video_statistics(data)
        )

        # Base-model links are only filled in, never replaced: where the
        # Research API (or anything else) already set them, that stays.
        video.scraped_at = timezone.now()
        if video.inferred_create_time is None:
            video.inferred_create_time = infer_publication_date_from_id(video.id_tiktok)
        if video.user_id is None:
            video.user = self._sync_user(data.get("author"))
        if video.music_id is None:
            video.music = self._sync_music(data.get("music"))
        video.save(
            update_fields=[
                "scraped_at",
                "inferred_create_time",
                "user",
                "music",
                "updated_at",
            ]
        )

        hashtags = self._sync_hashtags(data.get("challenges"))
        if hashtags:
            video.hashtags.add(*hashtags)

        self._mark(target, ScrapeTarget.Status.SUCCESS)

    @staticmethod
    def _mark(
        target: ScrapeTarget,
        status: ScrapeTarget.Status,
        error: Exception | None = None,
        tiktok_status_code: int | None = None,
    ) -> None:
        target.status = status
        target.attempts += 1
        target.last_attempted_at = timezone.now()
        target.last_error_type = type(error).__name__ if error else ""
        target.last_error_msg = str(error) if error else ""
        target.tiktok_status_code = tiktok_status_code
        target.save()

    @staticmethod
    def _sync_user(author: dict[str, Any] | None) -> TikTokUser | None:
        username = (author or {}).get("uniqueId")
        if not username:
            return None
        user, _ = TikTokUser.objects.get_or_create(
            name=username,
            defaults={
                "added_by": DataOrigins.SCRAPER,
                "id_tiktok": int_or_none(author.get("id")),
            },
        )
        return user

    @staticmethod
    def _sync_music(music_data: dict[str, Any] | None) -> TikTokMusic | None:
        music_id = int_or_none((music_data or {}).get("id"))
        if not music_id:
            return None
        music, _ = TikTokMusic.objects.get_or_create(
            id_tiktok=music_id,
            defaults={"added_by": DataOrigins.SCRAPER},
        )
        return music

    @staticmethod
    def _sync_hashtags(challenges: list[dict[str, Any]] | None) -> list[TikTokHashtag]:
        hashtags = []
        for challenge in challenges or []:
            name = challenge.get("title")
            if not name:
                continue
            hashtag, _ = TikTokHashtag.objects.get_or_create(
                name=name,
                defaults={
                    "added_by": DataOrigins.SCRAPER,
                    "id_tiktok": int_or_none(challenge.get("id")),
                },
            )
            hashtags.append(hashtag)
        return hashtags

    @classmethod
    def _clean_video(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Map scraped video data to VideoInfosScraped."""
        create_time_raw = int_or_none(data.get("createTime"))
        create_time = (
            datetime.fromtimestamp(create_time_raw, tz=UTC) if create_time_raw else None
        )
        file_data = data.get("video") or {}

        description = data.get("desc") or ""

        return {
            "description": description,
            "create_time": create_time,
            "duration": int_or_none(file_data.get("duration")),
            "video_mention_list": cls._mentions(description, data.get("textExtra")),
            # Passed on as scraped: no video with effects was available to
            # compare the structure against the Research API's.
            "effect_list": data.get("effectStickers"),
            "location_created": data.get("locationCreated") or "",
            "text_language": data.get("textLanguage") or "",
            "category_type": int_or_none(data.get("CategoryType")),
            "original_item": data.get("originalItem"),
            # "officalItem" is TikTok's spelling.
            "official_item": data.get("officalItem"),
            "private_item": data.get("privateItem"),
            "is_ad": data.get("isAd"),
            "diversification_labels": data.get("diversificationLabels"),
            "diversification_id": int_or_none(data.get("diversificationId")),
            "is_aigc": data.get("IsAigc"),
            "aigc_description": data.get("AIGCDescription") or "",
            "height": int_or_none(file_data.get("height")),
            "width": int_or_none(file_data.get("width")),
            "raw": cls._trim_raw(data),
        }

    @staticmethod
    def _mentions(
        description: str, text_extra: list[dict[str, Any]] | None
    ) -> list[str]:
        """Accounts mentioned in the description, as the Research API lists them.

        The Research API's ``video_mention_list`` holds each mention the way
        it is written in the description, without the "@" (which is a
        display name as often as a username). ``textExtra`` marks those
        spans with UTF-16 offsets into the description.
        """
        encoded = description.encode("utf-16-le")
        mentions = []
        for entry in text_extra or []:
            start, end = int_or_none(entry.get("start")), int_or_none(entry.get("end"))
            if not entry.get("userUniqueId") or start is None or end is None:
                continue
            # Two bytes per UTF-16 code unit.
            text = encoded[2 * start : 2 * end].decode("utf-16-le", errors="ignore")
            mention = text.strip().removeprefix("@")
            if mention:
                mentions.append(mention)
        return mentions

    @staticmethod
    def _clean_video_statistics(data: dict[str, Any]) -> dict[str, Any]:
        """Map scraped video data to VideoStatisticsScraped."""
        # "statsV2" carries every count (as strings); "stats" lacks reposts.
        stats = {**(data.get("stats") or {}), **(data.get("statsV2") or {})}
        return {
            "view_count": int_or_none(stats.get("playCount")),
            "like_count": int_or_none(stats.get("diggCount")),
            "comment_count": int_or_none(stats.get("commentCount")),
            "share_count": int_or_none(stats.get("shareCount")),
            "favorites_count": int_or_none(stats.get("collectCount")),
            "repost_count": int_or_none(stats.get("repostCount")),
        }

    @classmethod
    def _trim_raw(cls, value: Any) -> Any:  # noqa: ANN401
        """Copy of ``value`` without URLs and bulky encoding details."""
        if isinstance(value, dict):
            return {
                key: cls._trim_raw(item)
                for key, item in value.items()
                if key not in _RAW_EXCLUDED_KEYS and not cls._is_url(item)
            }
        if isinstance(value, list):
            return [cls._trim_raw(item) for item in value if not cls._is_url(item)]
        return value

    @staticmethod
    def _is_url(value: Any) -> bool:  # noqa: ANN401
        return isinstance(value, str) and value.startswith(("http://", "https://"))
