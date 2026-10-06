"""Persistence and queueing for scraped TikTok data.

This module is the single ingestion path for scraped data: nothing else
should create ``ScrapeTarget`` / ``*Scraped`` rows, so that queue state and
the "don't overwrite Research API data" policy stay consistent.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime, timedelta
from datetime import time as dt_time
from itertools import batched
from typing import TYPE_CHECKING, Any, NamedTuple, TypedDict

from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Exists, F, OuterRef, Q
from django.utils import timezone

from ddcs.metadata.models import (
    DataOrigins,
    TikTokHashtag,
    TikTokMusic,
    TikTokUser,
    TikTokVideo,
)
from ddcs.metadata.research_api.models import APIVideoInfos
from ddcs.metadata.scraper.config import WATCH_WINDOW_END, WATCH_WINDOW_START
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
    from collections.abc import Iterable, Mapping

logger = logging.getLogger(__name__)

_ENQUEUE_CHUNK_SIZE = 500
_RESET_CHUNK_SIZE = 500

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


class WatchHistoryScan(NamedTuple):
    # TikTok ID -> the donor's most recent view of that video in the window.
    last_watched: dict[int, datetime]
    views_in_window: int
    # Records that could not be used: no parsed date or no video ID.
    skipped_records: int


def scan_watch_history(
    watch_history: Iterable[Mapping[str, Any]] | None,
    start: date = WATCH_WINDOW_START,
    end: date = WATCH_WINDOW_END,
) -> WatchHistoryScan:
    """Find the videos one donor watched between ``start`` and ``end``.

    Both days are inclusive and taken in UTC, which is what donated
    timestamps are parsed as.
    """
    window_start = datetime.combine(start, dt_time.min, tzinfo=UTC)
    window_end = datetime.combine(end + timedelta(days=1), dt_time.min, tzinfo=UTC)

    last_watched: dict[int, datetime] = {}
    views_in_window = skipped_records = 0
    for record in watch_history or []:
        video_id = record.get("video_id")
        watched_at = record.get("date")
        if not isinstance(video_id, int) or not isinstance(watched_at, datetime):
            skipped_records += 1
            continue
        if watched_at.tzinfo is None:
            watched_at = watched_at.replace(tzinfo=UTC)
        if not window_start <= watched_at < window_end:
            continue
        views_in_window += 1
        previous = last_watched.get(video_id)
        if previous is None or watched_at > previous:
            last_watched[video_id] = watched_at
    return WatchHistoryScan(last_watched, views_in_window, skipped_records)


def watched_videos_in_window(
    watch_history: Iterable[Mapping[str, Any]] | None,
) -> dict[int, datetime]:
    """TikTok ID -> last view, for the videos one donor watched in the window."""
    return scan_watch_history(watch_history).last_watched


class EnqueueResult(NamedTuple):
    created: int
    # Existing targets whose count was raised.
    updated: int
    # Not queued because the Research API already delivered the video.
    covered_by_api: int


def enqueue_watched_videos(
    videos: Mapping[int, tuple[int, datetime | None]],
) -> EnqueueResult:
    """Queue watched videos for scraping, or raise their ranking.

    ``videos`` maps a TikTok ID to ``(count, last_watched_at)``: how many
    more donations show the video as watched within the watch window
    (1 when called for a single donation), and its most recent view there.
    The queue is worked off by highest count, then most recent view.

    This only ever adds: a video not queued yet gets a target, an already
    queued one has ``count`` added to its ``occurrence_count`` and keeps the
    later view. Calling it twice for the same donation therefore counts
    that donation twice; :func:`reset_watch_ranking` starts over.

    Videos without a ``TikTokVideo`` row get one; videos that already have
    Research API infos are skipped. A target's status is never touched, so
    nothing that was scraped is queued again.
    """
    created = updated = covered_by_api = 0

    for chunk in batched(videos, _ENQUEUE_CHUNK_SIZE):
        pk_by_id = _video_pks(chunk)
        uncovered = _without_api_infos(pk_by_id.values())
        covered_by_api += len(pk_by_id) - len(uncovered)
        existing = {
            target.video_id: target
            for target in ScrapeTarget.objects.filter(video_id__in=uncovered)
        }

        new, changed = [], []
        for pk, id_tiktok in uncovered.items():
            count, last_watched_at = videos[id_tiktok]
            target = existing.get(pk)
            if target is None:
                new.append(
                    ScrapeTarget(
                        video_id=pk,
                        occurrence_count=count,
                        last_watched_at=last_watched_at,
                    )
                )
                continue
            target.occurrence_count += count
            target.last_watched_at = max(
                filter(None, (target.last_watched_at, last_watched_at)),
                default=None,
            )
            changed.append(target)

        ScrapeTarget.objects.bulk_create(new, ignore_conflicts=True)
        ScrapeTarget.objects.bulk_update(
            changed, ["occurrence_count", "last_watched_at"]
        )
        created += len(new)
        updated += len(changed)

    return EnqueueResult(created, updated, covered_by_api)


def _video_pks(id_tiktoks: Iterable[int]) -> dict[int, int]:
    """TikTok ID -> primary key of the videos, creating rows that are missing."""

    def lookup(ids: Iterable[int]) -> dict[int, int]:
        return dict(
            TikTokVideo.objects.filter(id_tiktok__in=ids).values_list("id_tiktok", "pk")
        )

    pk_by_id = lookup(id_tiktoks)
    missing = [id_tiktok for id_tiktok in id_tiktoks if id_tiktok not in pk_by_id]
    if missing:
        TikTokVideo.objects.bulk_create(
            [
                TikTokVideo(id_tiktok=id_tiktok, added_by=DataOrigins.DONATION)
                for id_tiktok in missing
            ],
            ignore_conflicts=True,
        )
        pk_by_id.update(lookup(missing))
    return pk_by_id


def reset_watch_ranking() -> int:
    """Set the ranking of every target back to "not watched".

    Used before the watch histories are counted from scratch. Works in
    small steps, so the scraper is not held up by one long-running update.
    Returns the number of targets reset.
    """
    ranked = ScrapeTarget.objects.filter(
        Q(occurrence_count__gt=0) | Q(last_watched_at__isnull=False)
    )
    reset = 0
    while True:
        pks = list(ranked.values_list("pk", flat=True)[:_RESET_CHUNK_SIZE])
        if not pks:
            return reset
        reset += ScrapeTarget.objects.filter(pk__in=pks).update(
            occurrence_count=0, last_watched_at=None
        )


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
    # True if the batch stopped early because TikTok appears to be blocking
    # us; ``abort_reason`` says what was seen ("" if not aborted).
    aborted: bool
    abort_reason: str
    # Wall time of the batch and the resulting throughput. Every target a
    # page was requested for counts, whatever the outcome.
    seconds: float
    videos_per_minute: float


class LastScrapeRun(ScrapeBatchStats):
    finished_at: str  # ISO 8601


_LAST_RUN_CACHE_KEY = "metadata:scraper:last_run"
_LAST_RUN_CACHE_TIMEOUT = 60 * 60 * 25


def record_last_run(stats: ScrapeBatchStats) -> None:
    """Remember a finished run's statistics for the metadata dashboard."""
    # Plain JSON-compatible values only (hence the timestamp as a string).
    last_run: LastScrapeRun = {**stats, "finished_at": timezone.now().isoformat()}
    cache.set(_LAST_RUN_CACHE_KEY, last_run, _LAST_RUN_CACHE_TIMEOUT)


def get_last_run() -> LastScrapeRun | None:
    return cache.get(_LAST_RUN_CACHE_KEY)


ABORT_REASON_BLOCKED = "blocked"
ABORT_REASON_CONSECUTIVE_FAILURES = "consecutive_failures"

# Cool-down after aborted runs: 1 h after the first, doubling with every
# further abort in a row, at most 24 h.
COOLDOWN_BASE = timedelta(hours=1)
COOLDOWN_MAX = timedelta(hours=24)

_COOLDOWN_CACHE_KEY = "metadata:scraper:cooldown"
# Outlives the longest cool-down by far, so the abort count (and with it the
# escalation) is still known when scraping is tried again.
_COOLDOWN_CACHE_TIMEOUT = 60 * 60 * 24 * 7


class ScrapeCooldown(TypedDict):
    consecutive_aborts: int
    until: str  # ISO 8601


def get_cooldown() -> ScrapeCooldown | None:
    """Cool-down state since the last healthy run, whether still active or not."""
    return cache.get(_COOLDOWN_CACHE_KEY)


def cooldown_until() -> datetime | None:
    """When scraping may resume, or ``None`` if no cool-down is active."""
    cooldown = get_cooldown()
    if cooldown is None:
        return None
    until = datetime.fromisoformat(cooldown["until"])
    return until if until > timezone.now() else None


def register_abort() -> datetime:
    """Start (or lengthen) the cool-down after an aborted run.

    Returns the time until which scraping stays paused.
    """
    consecutive_aborts = (get_cooldown() or {}).get("consecutive_aborts", 0) + 1
    pause = min(COOLDOWN_BASE * 2 ** (consecutive_aborts - 1), COOLDOWN_MAX)
    until = timezone.now() + pause
    # Plain JSON-compatible values only.
    cooldown: ScrapeCooldown = {
        "consecutive_aborts": consecutive_aborts,
        "until": until.isoformat(),
    }
    cache.set(_COOLDOWN_CACHE_KEY, cooldown, _COOLDOWN_CACHE_TIMEOUT)
    return until


def clear_cooldown() -> None:
    """End the cool-down and forget previous aborts."""
    cache.delete(_COOLDOWN_CACHE_KEY)


class ScraperService:
    """Works off the ``ScrapeTarget`` queue and stores what was scraped."""

    # After this many blocked videos in a row the batch is abandoned:
    # continuing would only burn through the queue.
    CONSECUTIVE_BLOCKS_BEFORE_ABORT = 3
    # Same for videos that fail in a row without TikTok refusing outright
    # (no data in the page, unexpected structure, network errors). That
    # pattern is what a "soft" block or a changed page layout looks like
    # from here, and neither says anything about the individual videos.
    CONSECUTIVE_FAILURES_BEFORE_ABORT = 5
    # A failed target is not retried before this much time has passed.
    FAILED_RETRY_BACKOFF = timedelta(hours=6)

    def __init__(
        self,
        scraper: TikTokScraper | None = None,
        max_attempts: int | None = None,
        fetch_captions: bool | None = None,
    ) -> None:
        self.scraper = scraper or TikTokScraper(
            rate_delay=settings.TIKTOK_SCRAPER_RATE_DELAY,
            caption_delay=settings.TIKTOK_SCRAPER_CAPTION_DELAY,
            rate_jitter=settings.TIKTOK_SCRAPER_RATE_JITTER,
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
        """Scrape up to ``limit`` queued videos, in queue order.

        Queue order: videos more donors watched first, among those the
        ones watched most recently.

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
            "abort_reason": "",
            "seconds": 0.0,
            "videos_per_minute": 0.0,
        }
        started = time.monotonic()
        requested = 0
        targets = self._select_targets(limit, stats)
        results = self.scraper.scrape_video_list(
            [str(target.video.id_tiktok) for target in targets]
        )

        consecutive_blocks = 0
        # Failures are held back until it is clear whether they are
        # individual ones (pages are still being served: recorded as failed)
        # or the start of a streak (suspected block: targets left untouched).
        failure_streak: list[tuple[ScrapeTarget, Exception]] = []
        for target in targets:
            if deadline is not None and time.monotonic() > deadline:
                break
            result = next(results)
            requested += 1

            if result["success"]:
                consecutive_blocks = 0
                self._record_failures(failure_streak, stats)
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
                    stats["abort_reason"] = ABORT_REASON_BLOCKED
                    break
                continue

            if isinstance(error, TikTokItemUnavailableError):
                # A definite answer about this video, so pages are served.
                consecutive_blocks = 0
                self._record_failures(failure_streak, stats)
                self._mark(
                    target,
                    ScrapeTarget.Status.UNAVAILABLE,
                    error,
                    tiktok_status_code=int_or_none(error.status_code),
                )
                stats["unavailable"] += 1
                continue

            failure_streak.append((target, error))
            if len(failure_streak) >= self.CONSECUTIVE_FAILURES_BEFORE_ABORT:
                # Their targets stay pending, without an attempt counted.
                failure_streak.clear()
                stats["aborted"] = True
                stats["abort_reason"] = ABORT_REASON_CONSECUTIVE_FAILURES
                break

        # A streak too short to abort on: ordinary failures.
        self._record_failures(failure_streak, stats)

        seconds = time.monotonic() - started
        stats["seconds"] = round(seconds, 1)
        if seconds > 0:
            stats["videos_per_minute"] = round(requested / seconds * 60, 1)
        return stats

    def _record_failures(
        self,
        failure_streak: list[tuple[ScrapeTarget, Exception]],
        stats: ScrapeBatchStats,
    ) -> None:
        """Mark the held-back failures as failed and empty the list."""
        for target, error in failure_streak:
            self._mark(target, ScrapeTarget.Status.FAILED, error)
            stats["failed"] += 1
        failure_streak.clear()

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
            .order_by(
                "-occurrence_count",
                F("last_watched_at").desc(nulls_last=True),
                "id",
            )[:limit]
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
