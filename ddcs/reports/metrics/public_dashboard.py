"""Aggregate data functions for the public dashboard page."""

from __future__ import annotations

import contextlib
import csv
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from django.core.cache import cache
from django.db.models import Count, Sum
from django.utils import timezone

from ddcs.metadata.research_api.models import (
    APIVideoInfos,
    APIVideoStatistics,
)
from ddcs.reports.config import (
    BEHAVIOUR_METRICS_CSV_PATH,
    PUBLIC_POST_DATA_END_LAG_DAYS,
    PUBLIC_POST_DATA_START_DATE,
)
from ddcs.reports.metrics.account_metrics import _recode_party
from ddcs.reports.models import ParticipantReportStatistics
from ddcs.reports.user_types import USER_TYPES, assign_user_type
from ddcs.reports.utils import load_account_party_mapping

_TIERZEICHEN_CACHE_KEY = "reports:public_tierzeichen_dist"
_TIERZEICHEN_HISTORIC_CACHE_KEY = "reports:public_tierzeichen_historic"
_VIDEO_STATS_CACHE_KEY = "reports:public_video_stats"
_CACHE_TIMEOUT = 60 * 60 * 6


def _date_range() -> tuple[date, date]:
    end = timezone.now().date() - timedelta(days=PUBLIC_POST_DATA_END_LAG_DAYS)
    return PUBLIC_POST_DATA_START_DATE, end


def get_tierzeichen_distribution(
    *,
    force_refresh: bool = False,
) -> list[dict]:
    """Return [{animal, animal_id, count}, ...] sorted by count desc."""
    if not force_refresh:
        cached = cache.get(_TIERZEICHEN_CACHE_KEY)
        if cached is not None:
            return cached

    counts: Counter[str] = Counter()
    for stats in ParticipantReportStatistics.objects.only(
        "behaviour_comparisons"
    ).iterator():
        user_type = assign_user_type(stats.behaviour_comparisons or [])
        if user_type:
            counts[user_type["id"]] += 1

    result = []
    for type_id, count in counts.most_common():
        info = USER_TYPES.get(type_id)
        if info:
            result.append(
                {"animal": info["animal"], "animal_id": type_id, "count": count}
            )

    cache.set(_TIERZEICHEN_CACHE_KEY, result, _CACHE_TIMEOUT)
    return result


_DONATION_STATS_CACHE_KEY = "reports:public_donation_stats"


def _rate_like_from_comparisons(comparisons: list) -> float:
    for row in comparisons or []:
        if row.get("metric") == "rate_like":
            try:
                return float(row.get("value") or 0)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def get_donation_stats(*, force_refresh: bool = False) -> dict:
    """Aggregate Datenspende Kennzahlen across ParticipantReportStatistics.

    Likes are estimated as rate_like * videos_seen_count_total per donation.
    """
    if not force_refresh:
        cached = cache.get(_DONATION_STATS_CACHE_KEY)
        if cached is not None:
            return cached

    n_donations = 0
    total_videos = 0
    total_likes = 0.0
    for stats in ParticipantReportStatistics.objects.only(
        "videos_seen_count_total",
        "behaviour_comparisons",
    ).iterator():
        n_donations += 1
        videos = int(stats.videos_seen_count_total or 0)
        total_videos += videos
        total_likes += (
            _rate_like_from_comparisons(stats.behaviour_comparisons or []) * videos
        )

    total_likes_i = round(total_likes)
    result = {
        "n_donations": n_donations,
        "total_videos_watched": total_videos,
        "total_likes": total_likes_i,
        "avg_likes_per_video": round(total_likes_i / max(total_videos, 1), 2),
    }
    cache.set(_DONATION_STATS_CACHE_KEY, result, _CACHE_TIMEOUT)
    return result


_HISTORIC_METRICS = (
    "frac_instant_skip",
    "avg_session_length_sec",
    "night_activity_frac",
    "weekend_activity_frac",
    "rate_like",
    "frac_political_engagement",
)


def _load_historic_rows() -> list[dict[str, float]]:
    """Parse behaviour metrics CSV into list of metric dicts."""
    rows_data: list[dict[str, float]] = []
    try:
        with Path(BEHAVIOUR_METRICS_CSV_PATH).open(newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                parsed: dict[str, float] = {}
                for metric in _HISTORIC_METRICS:
                    val = row.get(metric, "")
                    if val:
                        with contextlib.suppress(ValueError):
                            parsed[metric] = float(val)
                if parsed:
                    rows_data.append(parsed)
    except FileNotFoundError:
        pass
    return rows_data


def _percentile_of(value: float, sorted_vals: list[float]) -> float:
    """Compute the percentile rank of value within sorted_vals."""
    n = len(sorted_vals)
    if n == 0:
        return 50.0
    count_below = sum(1 for v in sorted_vals if v < value)
    count_equal = sum(1 for v in sorted_vals if v == value)
    return ((count_below + count_equal * 0.5) / n) * 100.0


def _count_user_types_from_rows(rows_data: list[dict[str, float]]) -> Counter[str]:
    """Assign user types based on within-population percentiles."""
    sorted_values: dict[str, list[float]] = {}
    for metric in _HISTORIC_METRICS:
        vals = sorted(r[metric] for r in rows_data if metric in r)
        if vals:
            sorted_values[metric] = vals

    counts: Counter[str] = Counter()
    for row in rows_data:
        comparisons = []
        for metric in _HISTORIC_METRICS:
            if metric not in row:
                continue
            val = row[metric]
            if metric in sorted_values:
                pct = _percentile_of(val, sorted_values[metric])
            else:
                pct = 50.0
            comparisons.append({"metric": metric, "value": val, "percentile": pct})
        if not comparisons:
            continue
        user_type = assign_user_type(comparisons)
        if user_type:
            counts[user_type["id"]] += 1
    return counts


def get_tierzeichen_distribution_historic(
    *,
    force_refresh: bool = False,
) -> list[dict]:
    """Return Tierzeichen distribution from historic CSV (BTW 2025 data).

    Computes within-population percentiles for each metric, then uses
    assign_user_type with those percentiles for a balanced distribution.
    """
    if not force_refresh:
        cached = cache.get(_TIERZEICHEN_HISTORIC_CACHE_KEY)
        if cached is not None:
            return cached

    rows_data = _load_historic_rows()
    if not rows_data:
        cache.set(_TIERZEICHEN_HISTORIC_CACHE_KEY, [], _CACHE_TIMEOUT)
        return []

    counts = _count_user_types_from_rows(rows_data)

    result = [
        {"animal": info["animal"], "animal_id": type_id, "count": count}
        for type_id, count in counts.most_common()
        if (info := USER_TYPES.get(type_id))
    ]

    cache.set(_TIERZEICHEN_HISTORIC_CACHE_KEY, result, _CACHE_TIMEOUT)
    return result


def get_likes_per_party(
    *,
    force_refresh: bool = False,
    usernames_filter: set[str] | None = None,
) -> list[dict]:
    """Return [{party, total_likes, total_views, video_count, ...}, ...]."""
    cache_key = "reports:public_likes_per_party"
    if usernames_filter is None and not force_refresh:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    account_party_map = load_account_party_mapping()
    usernames = list(account_party_map.keys())
    if usernames_filter is not None:
        usernames = [u for u in usernames if u in usernames_filter]
    start, end = _date_range()

    qs = (
        APIVideoStatistics.objects.filter(
            video__user__name__in=usernames,
            video__api_infos__create_time__date__gte=start,
            video__api_infos__create_time__date__lte=end,
        )
        .values("video__user__name")
        .annotate(
            total_likes=Sum("like_count", default=0),
            total_views=Sum("view_count", default=0),
            video_count=Count("video__id_tiktok", distinct=True),
        )
    )

    party_agg: dict[str, dict] = {}
    for row in qs:
        username = row["video__user__name"]
        party = _recode_party(account_party_map.get(username, "Sonstige"))
        if party not in party_agg:
            party_agg[party] = {"total_likes": 0, "total_views": 0, "video_count": 0}
        party_agg[party]["total_likes"] += row["total_likes"]
        party_agg[party]["total_views"] += row["total_views"]
        party_agg[party]["video_count"] += row["video_count"]

    result = []
    for party, data in party_agg.items():
        vc = data["video_count"]
        result.append(
            {
                "party": party,
                "total_likes": data["total_likes"],
                "total_views": data["total_views"],
                "video_count": vc,
                "avg_likes_per_video": round(data["total_likes"] / max(vc, 1), 1),
                "avg_views_per_video": round(data["total_views"] / max(vc, 1), 1),
            }
        )

    result.sort(key=lambda x: x["total_likes"], reverse=True)
    if usernames_filter is None:
        cache.set(cache_key, result, _CACHE_TIMEOUT)
    return result


def get_monitored_video_stats(
    *,
    force_refresh: bool = False,
    usernames_filter: set[str] | None = None,
) -> dict:
    """Return aggregate stats for monitored accounts in the report window.

    Returns dict with keys: total_videos, total_likes, n_accounts, n_days,
    avg_videos_per_account_day, avg_likes_per_video.
    """
    if usernames_filter is None and not force_refresh:
        cached = cache.get(_VIDEO_STATS_CACHE_KEY)
        if cached is not None:
            return cached

    account_party_map = load_account_party_mapping()
    usernames = list(account_party_map.keys())
    if usernames_filter is not None:
        usernames = [u for u in usernames if u in usernames_filter]
    start, end = _date_range()

    infos_qs = APIVideoInfos.objects.filter(
        video__user__name__in=usernames,
        create_time__date__gte=start,
        create_time__date__lte=end,
    )
    total_videos = infos_qs.values("video__id_tiktok").distinct().count()

    total_likes = (
        APIVideoStatistics.objects.filter(
            video__user__name__in=usernames,
            video__api_infos__create_time__date__gte=start,
            video__api_infos__create_time__date__lte=end,
        ).aggregate(total=Sum("like_count", default=0))["total"]
        or 0
    )

    n_accounts = len(usernames)
    n_days = max((end - start).days + 1, 1)

    result = {
        "total_videos": total_videos,
        "total_likes": total_likes,
        "n_accounts": n_accounts,
        "n_days": n_days,
        "avg_videos_per_account_day": round(total_videos / (n_accounts * n_days), 2)
        if n_accounts
        else 0,
        "avg_likes_per_video": round(total_likes / max(total_videos, 1), 1),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }

    if usernames_filter is None:
        cache.set(_VIDEO_STATS_CACHE_KEY, result, _CACHE_TIMEOUT)
    return result
