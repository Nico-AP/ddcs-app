"""Query functions backing the internal metadata dashboard.

The sync-coverage, sync-video-count and monitored-count queries are cheap
and run live on every request. The video-level aggregates (origin counts, classification
coverage) scan millions of rows, so they are never computed in a request:
``refresh_dashboard_snapshot`` computes them (from a Celery task, see
``ddcs.metadata.tasks.refresh_metadata_dashboard``) and stores the result in
the cache; the view only reads ``get_dashboard_snapshot``.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import TypedDict

from django.core.cache import cache
from django.db.models import Count, Exists, Max, OuterRef, Q, QuerySet
from django.db.models.functions import TruncDate
from django.utils import timezone

from ddcs.metadata.models import (
    Keyword,
    ResearchAPIQueryTracker,
    SyncAttempt,
    TikTokUser,
    TikTokVideo,
    TikTokVideoClassification,
)
from ddcs.metadata.research_api.models import APIVideoInfos
from ddcs.metadata.scraper.models import ScrapeTarget
from ddcs.metadata.scraper.service import (
    LastScrapeRun,
    cooldown_until,
    get_cooldown,
    get_last_run,
)

DEFAULT_WINDOW_DAYS = 90

_SNAPSHOT_CACHE_KEY = "metadata:dashboard:snapshot"
# Slightly over a day: an hourly Celery task is expected to overwrite this key
# long before it expires; the timeout is just a safety net if that task
# doesn't run.
_SNAPSHOT_CACHE_TIMEOUT = 60 * 60 * 25


def default_date_range() -> tuple[date, date]:
    """Last ``DEFAULT_WINDOW_DAYS`` days, inclusive of today."""
    end = timezone.localdate()
    start = end - timedelta(days=DEFAULT_WINDOW_DAYS - 1)
    return start, end


def _all_dates(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


class OriginCount(TypedDict):
    added_by: str
    total: int
    with_api_info: int
    without_api_info: int


def get_video_counts_by_origin() -> list[OriginCount]:
    """Video counts grouped by ``DataOrigin``, split by APIVideoInfos presence.

    Two plain aggregates instead of one ``COUNT(...) FILTER (WHERE EXISTS
    (...))``: Postgres runs an ``EXISTS`` inside an aggregate as a per-row
    subplan (one index probe per video), whereas an ``EXISTS`` in ``WHERE``
    becomes a single semi-join. That matters with millions of videos. The
    semi-join (rather than joining ``api_infos`` directly) also avoids
    fanning out videos with multiple API-info snapshots.
    """
    totals = {
        row["added_by"]: row["total"]
        for row in TikTokVideo.objects.values("added_by").annotate(total=Count("pk"))
    }
    with_api_info = {
        row["added_by"]: row["total"]
        for row in TikTokVideo.objects.filter(
            Exists(APIVideoInfos.objects.filter(video=OuterRef("pk")))
        )
        .values("added_by")
        .annotate(total=Count("pk"))
    }
    return [
        {
            "added_by": origin,
            "total": total,
            "with_api_info": with_api_info.get(origin, 0),
            "without_api_info": total - with_api_info.get(origin, 0),
        }
        for origin, total in sorted(totals.items())
    ]


class SyncCoverageDay(TypedDict):
    date: date
    attempted: int
    succeeded: int


def get_sync_coverage(
    target_field: str, start: date, end: date
) -> list[SyncCoverageDay]:
    """Daily Research API sync coverage for ``target_field`` ("keyword" or "user").

    A day with no ``SyncAttempt`` rows at all (rather than only failed ones)
    is a real gap in the sync pipeline, so missing days are filled with 0s
    (unlike the "unknown vs. confirmed zero" distinction used for video
    counts elsewhere — there is no ambiguity here: no attempt row means the
    sync job did not run for that item/day).
    """
    rows = (
        SyncAttempt.objects.filter(
            **{f"{target_field}__isnull": False},
            target_date__range=(start, end),
        )
        .values("target_date")
        .annotate(
            attempted=Count(target_field, distinct=True),
            succeeded=Count(
                target_field,
                filter=Q(status=SyncAttempt.Status.SUCCESS),
                distinct=True,
            ),
        )
        .order_by("target_date")
    )
    by_date = {row["target_date"]: row for row in rows}
    return [
        {
            "date": day,
            "attempted": by_date.get(day, {}).get("attempted", 0),
            "succeeded": by_date.get(day, {}).get("succeeded", 0),
        }
        for day in _all_dates(start, end)
    ]


class SyncVideoCountDay(TypedDict):
    date: date
    # ``None``: no run reported a result for this day (as opposed to 0: the
    # sync ran and the API returned nothing).
    videos: int | None
    pages: int | None


# ``ResearchAPIQueryTracker.query_function`` of the sync runs per target
# field; see the ``_SyncTargetConfig`` instances in
# ``ddcs.metadata.research_api.tasks``.
_SYNC_TASK_NAMES = {"user": "daily_sync_users", "keyword": "daily_sync_keywords"}


def get_sync_video_counts(
    target_field: str, start: date, end: date
) -> list[SyncVideoCountDay]:
    """Videos the Research API returned per synced day, for ``target_field``.

    Read from the run-level stats each sync stores on its
    ``ResearchAPIQueryTracker`` (a handful of rows per day), so no video
    table is touched and this is cheap enough to run live. Runs for the same
    target date (retries, backfills, forced resyncs) are summed, so this is
    "videos returned by the API", which can exceed the number of distinct
    videos when items were queried more than once.
    """
    lo, _ = _day_bounds(start, end)
    # A run never targets a future date, so runs for ``start`` or later
    # cannot have started before ``start``.
    trackers = ResearchAPIQueryTracker.objects.filter(
        query_function=_SYNC_TASK_NAMES[target_field],
        start_time__gte=lo,
        query_result__isnull=False,
    ).values_list("query_parameters", "query_result")

    by_date: dict[date, dict[str, int]] = {}
    for parameters, result in trackers:
        try:
            day = date.fromisoformat(parameters["target_date"])
        except (KeyError, TypeError, ValueError):
            continue
        if not isinstance(result, dict) or not start <= day <= end:
            continue
        counts = by_date.setdefault(day, {"videos": 0, "pages": 0})
        counts["videos"] += result.get("videos_retrieved") or 0
        counts["pages"] += result.get("pages_retrieved") or 0

    return [
        {
            "date": day,
            "videos": by_date[day]["videos"] if day in by_date else None,
            "pages": by_date[day]["pages"] if day in by_date else None,
        }
        for day in _all_dates(start, end)
    ]


class SuspiciousSyncDay(TypedDict):
    date: date
    succeeded: int
    pages: int


def get_suspicious_sync_days(
    coverage: list[SyncCoverageDay], video_counts: list[SyncVideoCountDay]
) -> list[SuspiciousSyncDay]:
    """Days on which items synced successfully but no videos came back.

    Newest first. Days without a reported result (``videos`` is ``None``)
    are unknown rather than empty, so they are not listed.
    """
    succeeded = {day["date"]: day["succeeded"] for day in coverage}
    return [
        {
            "date": day["date"],
            "succeeded": succeeded[day["date"]],
            "pages": day["pages"] or 0,
        }
        for day in reversed(video_counts)
        if day["videos"] == 0 and succeeded.get(day["date"], 0) > 0
    ]


def get_monitored_keyword_count() -> int:
    return Keyword.objects.filter(monitor_api=True).count()


def get_monitored_user_count() -> int:
    return TikTokUser.objects.filter(monitor_api=True).count()


class ScraperQueueStatus(TypedDict):
    status: str
    label: str
    count: int


class ScraperCooldown(TypedDict):
    until: datetime
    consecutive_aborts: int


class ScraperQueue(TypedDict):
    total: int
    by_status: list[ScraperQueueStatus]
    last_success_at: datetime | None
    # Statistics of the most recent scraping run, if one finished recently.
    last_run: LastScrapeRun | None
    # Set while scraping is paused after aborted runs.
    cooldown: ScraperCooldown | None


def get_scraper_queue() -> ScraperQueue:
    """Scraping queue size per status. The queue table is small: runs live."""
    counts = dict(
        ScrapeTarget.objects.values_list("status").annotate(n=Count("pk")).order_by()
    )
    last_success_at = ScrapeTarget.objects.filter(
        status=ScrapeTarget.Status.SUCCESS
    ).aggregate(last=Max("last_attempted_at"))["last"]
    return {
        "total": sum(counts.values()),
        "by_status": [
            {
                "status": status.value,
                "label": status.label,
                "count": counts.get(status, 0),
            }
            for status in ScrapeTarget.Status
        ],
        "last_success_at": last_success_at,
        "last_run": get_last_run(),
        "cooldown": _active_scraper_cooldown(),
    }


def _active_scraper_cooldown() -> ScraperCooldown | None:
    until = cooldown_until()
    if until is None:
        return None
    return {
        "until": until,
        "consecutive_aborts": get_cooldown()["consecutive_aborts"],
    }


class ClassificationCoverageDay(TypedDict):
    date: date
    total: int
    classified: int


def _day_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """Aware ``[lo, hi)`` datetimes covering ``start``..``end`` inclusive."""
    lo = timezone.make_aware(datetime.combine(start, time.min))
    hi = timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min))
    return lo, hi


class ClassificationCounts(TypedDict):
    total: int
    classified: int


def _videos_per_publish_date(infos: QuerySet[APIVideoInfos]) -> dict[str, int]:
    return {
        row["pub_date"].isoformat(): row["n"]
        for row in infos.annotate(pub_date=TruncDate("create_time"))
        .values("pub_date")
        .annotate(n=Count("video_id", distinct=True))
    }


def _classification_counts_by_date(
    start: date | None = None, end: date | None = None
) -> dict[str, ClassificationCounts]:
    """Per-publish-date video counts (total / classified), optionally bounded.

    Keyed by ISO date string rather than ``date``, so the result can be
    cached (and inspected by tooling) as plain JSON-compatible data.

    Aggregates straight from ``APIVideoInfos`` on ``video_id`` and never
    touches the ``TikTokVideo`` table: with the covering
    ``(create_time) INCLUDE (video_id)`` index both queries can be answered
    from the index alone.

    Two plain aggregates instead of one with a filtered count, for the same
    reason as in ``get_video_counts_by_origin``: an ``EXISTS`` in ``WHERE``
    is a single semi-join, whereas inside an aggregate it is a per-row
    subplan. ``distinct=True`` keeps a video with several snapshots on the
    same publish date from being counted twice.
    """
    infos = APIVideoInfos.objects.filter(create_time__isnull=False)
    if start is not None and end is not None:
        lo, hi = _day_bounds(start, end)
        infos = infos.filter(create_time__gte=lo, create_time__lt=hi)

    totals = _videos_per_publish_date(infos)
    classified = _videos_per_publish_date(
        infos.filter(
            Exists(
                TikTokVideoClassification.objects.filter(video_id=OuterRef("video_id"))
            )
        )
    )
    return {
        day: {"total": total, "classified": classified.get(day, 0)}
        for day, total in totals.items()
    }


def fill_classification_coverage(
    by_date: dict[str, ClassificationCounts], start: date, end: date
) -> list[ClassificationCoverageDay]:
    """One entry per day in ``start``..``end``; days without videos are 0."""
    empty: ClassificationCounts = {"total": 0, "classified": 0}
    return [
        {"date": day, **by_date.get(day.isoformat(), empty)}
        for day in _all_dates(start, end)
    ]


def get_classification_coverage(
    start: date, end: date
) -> list[ClassificationCoverageDay]:
    """Daily classification coverage for videos that have APIVideoInfos.

    "Date" is the video's TikTok-reported publish date
    (``APIVideoInfos.create_time``). The Research API service stores at most
    one snapshot per video, so there is no "latest snapshot" to pick; should
    a video ever have snapshots with different publish dates, it is counted
    on each of them.
    """
    return fill_classification_coverage(
        _classification_counts_by_date(start, end), start, end
    )


class DashboardSnapshot(TypedDict):
    computed_at: datetime
    origin_counts: list[OriginCount]
    # Whole history at day grain, so any requested range is a dict lookup.
    classification_by_date: dict[str, ClassificationCounts]


def get_dashboard_snapshot() -> DashboardSnapshot | None:
    """The cached expensive aggregates, or ``None`` if not computed yet.

    Never computes anything, so it is safe to call from a request.
    """
    return cache.get(_SNAPSHOT_CACHE_KEY)


def refresh_dashboard_snapshot() -> DashboardSnapshot:
    """Recompute and cache the expensive aggregates. Slow; not for requests."""
    snapshot: DashboardSnapshot = {
        "computed_at": timezone.now(),
        "origin_counts": get_video_counts_by_origin(),
        "classification_by_date": _classification_counts_by_date(),
    }
    cache.set(_SNAPSHOT_CACHE_KEY, snapshot, _SNAPSHOT_CACHE_TIMEOUT)
    return snapshot
