"""Effective date window for the public post-count datasets."""

from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Max, Min
from django.utils import timezone

from ddcs.metadata.research_api.models import APIVideoInfos
from ddcs.reports.config import (
    PUBLIC_POST_DATA_END_LAG_DAYS,
    PUBLIC_POST_DATA_START_DATE,
)
from ddcs.reports.utils import load_account_party_mapping


def configured_date_range() -> tuple[date, date]:
    """The window the public plots are meant to cover."""
    end = timezone.now().date() - timedelta(days=PUBLIC_POST_DATA_END_LAG_DAYS)
    return PUBLIC_POST_DATA_START_DATE, end


def _monitored_usernames() -> list[str]:
    return list(load_account_party_mapping().keys())


def _has_videos_between(usernames: list[str], start: date, end: date) -> bool:
    return APIVideoInfos.objects.filter(
        video__user__name__in=usernames,
        create_time__date__gte=start,
        create_time__date__lte=end,
    ).exists()


def _monitored_video_bounds(usernames: list[str]) -> tuple[date, date] | None:
    bounds = APIVideoInfos.objects.filter(video__user__name__in=usernames).aggregate(
        first=Min("create_time"), last=Max("create_time")
    )
    first, last = bounds["first"], bounds["last"]
    if first is None or last is None:
        return None
    return timezone.localdate(first), timezone.localdate(last)


def public_post_data_date_range() -> tuple[date, date]:
    """Configured window, or the full available range when it holds no data.

    Staging databases only carry pre-launch videos, so the configured window
    is empty there and every public plot renders as "no data". Widening to
    whatever the database actually holds keeps those environments verifiable.
    Production has videos inside the configured window, so this stays inert.
    """
    start, end = configured_date_range()
    usernames = _monitored_usernames()
    if _has_videos_between(usernames, start, end):
        return start, end
    return _monitored_video_bounds(usernames) or (start, end)
