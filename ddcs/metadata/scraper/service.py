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
from django.db.models import Exists, OuterRef, Q, TextChoices
from django.utils import timezone

from ddcs.metadata.models import (
    DataOrigins,
    TikTokHashtag,
    TikTokMusic,
    TikTokUser,
    TikTokVideo,
)
from ddcs.metadata.research_api.models import APIVideoInfos
from ddcs.metadata.scraper.config import (
    PRIORITY_MIN_OCCURRENCES,
    PRIORITY_WATCHED_SINCE,
    WATCH_WINDOW_END,
    WATCH_WINDOW_START,
)
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
    from collections.abc import Callable, Iterable, Mapping

    from django.contrib.auth.models import AbstractBaseUser
    from django.db.models import QuerySet

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


# ``claimed_by_label`` of targets the built-in scraper has leased.
INTERNAL_SCRAPER_LABEL = "internal"
# Lease the built-in scraper takes on its batch; a run lasts an hour at most.
INTERNAL_LEASE = timedelta(hours=1)

# A failed target is not retried before this much time has passed.
FAILED_RETRY_BACKOFF = timedelta(hours=6)


def _first_of(
    querysets: Iterable[QuerySet[ScrapeTarget]],
    limit: int,
    key: Callable[[ScrapeTarget], Any],
) -> list[ScrapeTarget]:
    """The first ``limit`` targets of several equally ordered querysets.

    ``key`` has to sort targets the way the querysets are ordered.
    """
    candidates = [target for queryset in querysets for target in queryset[:limit]]
    return sorted(candidates, key=key)[:limit]


@transaction.atomic
def _claim_due_targets(  # noqa: PLR0913
    limit: int,
    *,
    max_attempts: int,
    lease: timedelta,
    retry_backoff: timedelta = FAILED_RETRY_BACKOFF,
    user: AbstractBaseUser | None = None,
    label: str = "",
) -> tuple[list[ScrapeTarget], int, datetime]:
    """Take the next ``limit`` due targets off the queue and lease them.

    Queue order: first the videos at least ``PRIORITY_MIN_OCCURRENCES``
    donors watched since ``PRIORITY_WATCHED_SINCE`` (most donors first),
    then all others by most recent view. Targets somebody else holds a
    running lease on are passed over.

    Returns the leased targets, the number of targets that were dropped
    because the Research API has their video now, and the time the lease
    runs out.
    """
    now = timezone.now()
    # Pending targets and failed ones due for a retry are read separately:
    # each read then follows one of the queue indexes
    # (``ScrapeTarget.Meta.indexes``) and stops after ``limit`` rows. Asked
    # for in one query, the whole queue is sorted on every claim.
    due = [
        ScrapeTarget.objects.filter(status_filter)
        .filter(Q(claimed_until__isnull=True) | Q(claimed_until__lt=now))
        .select_related("video")
        # Two scrapers asking at the same moment get different targets
        # instead of waiting for each other.
        .select_for_update(skip_locked=True, of=("self",))
        for status_filter in (
            Q(status=ScrapeTarget.Status.PENDING),
            Q(
                status=ScrapeTarget.Status.FAILED,
                attempts__lt=max_attempts,
                last_attempted_at__lt=now - retry_backoff,
            ),
        )
    ]

    # First the videos many donors saw recently, most donors first.
    priority = Q(
        occurrence_count__gte=PRIORITY_MIN_OCCURRENCES,
        last_watched_at__gte=datetime.combine(
            PRIORITY_WATCHED_SINCE, dt_time.min, tzinfo=UTC
        ),
    )
    targets = _first_of(
        [
            queryset.filter(priority).order_by(
                "-occurrence_count", "-last_watched_at", "id"
            )
            for queryset in due
        ],
        limit,
        key=lambda t: (-t.occurrence_count, -t.last_watched_at.timestamp(), t.pk),
    )
    # Once those run out, everything else by most recent view. Only
    # reached when the priority group fits the batch, so excluding the
    # targets picked above excludes the whole group.
    if len(targets) < limit:
        picked = [t.pk for t in targets]
        targets += _first_of(
            [
                queryset.exclude(pk__in=picked)
                .filter(last_watched_at__isnull=False)
                .order_by("-last_watched_at", "id")
                for queryset in due
            ],
            limit - len(targets),
            key=lambda t: (-t.last_watched_at.timestamp(), t.pk),
        )
    # Targets without a watch date come last. Read on their own because the
    # queue indexes leave them out.
    if len(targets) < limit:
        picked = [t.pk for t in targets]
        targets += _first_of(
            [
                queryset.exclude(pk__in=picked)
                .filter(last_watched_at__isnull=True)
                .order_by("id")
                for queryset in due
            ],
            limit - len(targets),
            key=lambda t: t.pk,
        )

    # The Research API may have delivered some of them since they were
    # queued; those no longer need scraping.
    covered_by_api = 0
    uncovered: list[ScrapeTarget] = []
    for chunk in batched(targets, _ENQUEUE_CHUNK_SIZE):
        still_missing = set(_without_api_infos(t.video_id for t in chunk))
        covered = [t.pk for t in chunk if t.video_id not in still_missing]
        if covered:
            ScrapeTarget.objects.filter(pk__in=covered).update(
                status=ScrapeTarget.Status.COVERED_BY_API,
                updated_at=now,
            )
            covered_by_api += len(covered)
        uncovered.extend(t for t in chunk if t.video_id in still_missing)

    claimed_until = now + lease
    for chunk in batched(uncovered, _ENQUEUE_CHUNK_SIZE):
        ScrapeTarget.objects.filter(pk__in=[t.pk for t in chunk]).update(
            claimed_by=user,
            claimed_by_label=label,
            claimed_until=claimed_until,
            updated_at=now,
        )
        for target in chunk:
            target.claimed_by = user
            target.claimed_by_label = label
            target.claimed_until = claimed_until
    return uncovered, covered_by_api, claimed_until


def claim_targets(
    user: AbstractBaseUser, limit: int, label: str = ""
) -> tuple[list[ScrapeTarget], datetime]:
    """Lease the next ``limit`` due targets to an external scraper.

    ``label`` is the name the scraper gave itself; it is stored for
    information only. Returns the targets in queue order and the time the
    lease runs out. A target no result arrives for returns to the queue
    then.
    """
    targets, _, claimed_until = _claim_due_targets(
        limit,
        max_attempts=settings.TIKTOK_SCRAPER_MAX_ATTEMPTS,
        lease=timedelta(minutes=settings.TIKTOK_SCRAPER_EXTERNAL_LEASE_MINUTES),
        user=user,
        label=label,
    )
    return targets, claimed_until


class ExternalOutcome(TextChoices):
    """What an external scraper reports for a target."""

    SUCCESS = "success"
    # TikTok reports the video as gone/private.
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    # Not scraped (e.g. the scraper got blocked): back to the queue, no
    # attempt counted.
    RELEASED = "released"


class ExternalResultStatus(TextChoices):
    """What became of a result an external scraper submitted."""

    STORED = "stored"
    RECORDED = "recorded"
    RELEASED = "released"
    ALREADY_DONE = "already_done"
    NOT_CLAIMED = "not_claimed"
    INVALID = "invalid"


class ExternalScrapeError(Exception):
    """A failure an external scraper reported, in its own words."""


_FINAL_STATUSES = (
    ScrapeTarget.Status.SUCCESS,
    ScrapeTarget.Status.UNAVAILABLE,
    ScrapeTarget.Status.COVERED_BY_API,
)


@transaction.atomic
def record_external_result(
    user: AbstractBaseUser, result: Mapping[str, Any]
) -> tuple[ExternalResultStatus, str]:
    """Store what an external scraper reports for one target it claimed.

    ``result`` has the shape validated by
    ``ddcs.metadata.scraper.serializers.ScrapeResultSerializer``. Only the
    account that claimed a target may report on it. A lease that ran out
    does not matter as long as nobody else has taken or finished the
    target since.

    Returns what was done and a detail message (empty unless there is
    something to explain).
    """
    status = ExternalResultStatus
    id_tiktok = result["id_tiktok"]
    target = (
        ScrapeTarget.objects.select_for_update(of=("self",))
        .select_related("video")
        .filter(video__id_tiktok=id_tiktok, claimed_by=user)
        .first()
    )
    if target is None:
        return status.NOT_CLAIMED, "No target for this video is claimed by you."
    if target.status in _FINAL_STATUSES:
        return status.ALREADY_DONE, f"Target is already '{target.status}'."

    outcome = result["outcome"]
    if outcome == ExternalOutcome.RELEASED:
        target.claimed_until = None
        target.save(update_fields=["claimed_until", "updated_at"])
        return status.RELEASED, ""

    if outcome == ExternalOutcome.UNAVAILABLE:
        status_code = result.get("tiktok_status_code")
        ScraperService._mark(  # noqa: SLF001
            target,
            ScrapeTarget.Status.UNAVAILABLE,
            TikTokItemUnavailableError(status_code, result.get("error_msg") or None),
            tiktok_status_code=status_code,
        )
        return status.RECORDED, ""

    if outcome == ExternalOutcome.FAILED:
        error = ExternalScrapeError(result.get("error_msg") or "")
        ScraperService._mark(  # noqa: SLF001
            target,
            ScrapeTarget.Status.FAILED,
            error,
            error_type=result.get("error_type") or None,
        )
        return status.RECORDED, ""

    return _store_external_success(target, result)


def _store_external_success(
    target: ScrapeTarget, result: Mapping[str, Any]
) -> tuple[ExternalResultStatus, str]:
    status = ExternalResultStatus
    id_tiktok = target.video.id_tiktok
    data = result.get("data")
    if not isinstance(data, dict) or str(data.get("id")) != str(id_tiktok):
        # Most likely the payload of another video: don't touch the target.
        return status.INVALID, "'data' must be the video's itemStruct ('id' differs)."

    try:
        ScraperService._store(  # noqa: SLF001
            target, data, _external_caption(result.get("caption"))
        )
    except Exception as e:
        logger.exception(
            "Could not store externally scraped data for video %s.", id_tiktok
        )
        ScraperService._mark(target, ScrapeTarget.Status.FAILED, e)  # noqa: SLF001
        return status.INVALID, f"Data could not be stored ({type(e).__name__})."
    return status.STORED, ""


def _external_caption(caption: Mapping[str, Any] | None) -> dict[str, Any]:
    """An externally scraped caption as ``VideoInfosScraped`` fields."""
    status = VideoInfosScraped.CaptionStatus
    if not caption:
        return {"caption_status": status.NOT_REQUESTED}
    if caption["status"] != status.FETCHED:
        return {"caption_status": caption["status"]}
    return {
        "caption_status": status.FETCHED,
        "voice_to_text": TikTokParser.webvtt_to_text(caption["vtt"]),
        "caption_vtt": caption["vtt"],
        "caption_language": caption.get("language") or "",
        "caption_is_auto_generated": caption.get("is_auto_generated"),
    }


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
    FAILED_RETRY_BACKOFF = FAILED_RETRY_BACKOFF

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

        Queue order: first the videos at least ``PRIORITY_MIN_OCCURRENCES``
        donors watched since ``PRIORITY_WATCHED_SINCE`` (most donors first),
        then all others by most recent view.

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
        # Whatever was not worked on (deadline, abort, blocked) goes back to
        # the queue right away instead of waiting for the lease to run out.
        self._release(targets)

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
        targets, covered_by_api, _ = _claim_due_targets(
            limit,
            max_attempts=self.max_attempts,
            retry_backoff=self.FAILED_RETRY_BACKOFF,
            lease=INTERNAL_LEASE,
            label=INTERNAL_SCRAPER_LABEL,
        )
        stats["covered_by_api"] += covered_by_api
        return targets

    @staticmethod
    def _release(targets: Iterable[ScrapeTarget]) -> None:
        """Give back the targets of a batch that were not worked on."""
        leftover = [t.pk for t in targets if t.claimed_until is not None]
        for chunk in batched(leftover, _ENQUEUE_CHUNK_SIZE):
            ScrapeTarget.objects.filter(pk__in=chunk).update(claimed_until=None)

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

    @classmethod
    @transaction.atomic
    def _store(
        cls, target: ScrapeTarget, data: dict[str, Any], caption: dict[str, Any]
    ) -> None:
        video = target.video
        VideoInfosScraped.objects.create(
            video=video, **cls._clean_video(data), **caption
        )
        VideoStatisticsScraped.objects.create(
            video=video, **cls._clean_video_statistics(data)
        )

        # Base-model links are only filled in, never replaced: where the
        # Research API (or anything else) already set them, that stays.
        video.scraped_at = timezone.now()
        if video.inferred_create_time is None:
            video.inferred_create_time = infer_publication_date_from_id(video.id_tiktok)
        if video.user_id is None:
            video.user = cls._sync_user(data.get("author"))
        if video.music_id is None:
            video.music = cls._sync_music(data.get("music"))
        video.save(
            update_fields=[
                "scraped_at",
                "inferred_create_time",
                "user",
                "music",
                "updated_at",
            ]
        )

        hashtags = cls._sync_hashtags(data.get("challenges"))
        if hashtags:
            video.hashtags.add(*hashtags)

        cls._mark(target, ScrapeTarget.Status.SUCCESS)

    @staticmethod
    def _mark(
        target: ScrapeTarget,
        status: ScrapeTarget.Status,
        error: Exception | None = None,
        tiktok_status_code: int | None = None,
        error_type: str | None = None,
    ) -> None:
        target.status = status
        target.attempts += 1
        target.last_attempted_at = timezone.now()
        # ``error_type`` names an error that happened elsewhere (an external
        # scraper), where there is no exception class to take it from.
        target.last_error_type = error_type or (type(error).__name__ if error else "")
        target.last_error_msg = str(error) if error else ""
        target.tiktok_status_code = tiktok_status_code
        # Worked on: the lease ends, who held it stays on record.
        target.claimed_until = None
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
