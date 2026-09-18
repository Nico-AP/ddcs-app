"""Query functions backing the internal metadata dashboard.

No caching here (unlike ``ddcs.reports.metrics``, which caches for a
high-traffic public dashboard) — this is a low-traffic, superuser-only page,
so querying live keeps the numbers always current.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TypedDict

from django.db.models import Count, Exists, OuterRef, Q, Subquery
from django.db.models.functions import TruncDate
from django.utils import timezone

from ddcs.metadata.models import (
    Keyword,
    SyncAttempt,
    TikTokUser,
    TikTokVideo,
    TikTokVideoClassification,
)
from ddcs.metadata.research_api.models import APIVideoInfos

DEFAULT_WINDOW_DAYS = 90


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

    Uses an ``Exists`` subquery annotation (same approach as
    ``TikTokVideoFilter.filter_has_api_infos`` in ``ddcs/metadata/filters.py``)
    rather than joining on the one-to-many ``api_infos`` relation directly,
    which would fan out rows for videos with multiple API-info snapshots.
    """
    has_api_info = Exists(APIVideoInfos.objects.filter(video=OuterRef("pk")))
    rows = (
        TikTokVideo.objects.annotate(has_api_info=has_api_info)
        .values("added_by")
        .annotate(
            total=Count("id"),
            with_api_info=Count("id", filter=Q(has_api_info=True)),
        )
        .order_by("added_by")
    )
    return [
        {
            "added_by": row["added_by"],
            "total": row["total"],
            "with_api_info": row["with_api_info"],
            "without_api_info": row["total"] - row["with_api_info"],
        }
        for row in rows
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


def get_monitored_keyword_count() -> int:
    return Keyword.objects.filter(monitor_api=True).count()


def get_monitored_user_count() -> int:
    return TikTokUser.objects.filter(monitor_api=True).count()


class ClassificationCoverageDay(TypedDict):
    date: date
    total: int
    classified: int


def get_classification_coverage(
    start: date, end: date
) -> list[ClassificationCoverageDay]:
    """Daily classification coverage for videos that have APIVideoInfos.

    "Date" is the video's TikTok-reported publish date, taken from the most
    recently fetched ``APIVideoInfos`` snapshot (mirrors the
    ``latest_create_time`` annotation in ``TikTokVideoList.get_queryset``).
    ``TikTokVideoClassification.video`` is a genuine one-to-one field, so
    joining it does not fan out rows the way ``api_infos`` would.
    """
    latest_info = APIVideoInfos.objects.filter(video=OuterRef("pk")).order_by(
        "-created_at"
    )
    has_classification = Exists(
        TikTokVideoClassification.objects.filter(video=OuterRef("pk"))
    )
    rows = (
        TikTokVideo.objects.annotate(
            latest_create_time=Subquery(latest_info.values("create_time")[:1]),
            is_classified=has_classification,
        )
        .filter(latest_create_time__date__range=(start, end))
        .annotate(pub_date=TruncDate("latest_create_time"))
        .values("pub_date")
        .annotate(
            total=Count("id"),
            classified=Count("id", filter=Q(is_classified=True)),
        )
        .order_by("pub_date")
    )
    by_date = {row["pub_date"]: row for row in rows}
    return [
        {
            "date": day,
            "total": by_date.get(day, {}).get("total", 0),
            "classified": by_date.get(day, {}).get("classified", 0),
        }
        for day in _all_dates(start, end)
    ]
