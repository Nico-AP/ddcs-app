"""Behaviour metrics from donated watch history, compared to a reference population."""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings

from ddcs.reports.config import REPORT_FIRST_DATE_TO_INCLUDE

if TYPE_CHECKING:
    from ddcs.core.types import TikTokUserData, WatchHistoryRecord
    from ddcs.reports.types import BehaviourComparisonRecord

_DATA_DIR = Path(__file__).parent / "data"
_DEFAULT_BEHAVIOUR_METRICS_CSV = _DATA_DIR / "behaviour_metrics_per_participant.csv"

_SATURDAY_WEEKDAY = 5
_NIGHT_HOUR_START = 22
_NIGHT_HOUR_END = 6

# Profile metrics shown in the report (totals omitted from the UI).
PROFILE_METRICS: list[str] = [
    "avg_watch_per_active_day",
    "avg_active_hours_per_day",
    "weekend_activity_frac",
    "night_activity_frac",
    "peak_activity_hour",
]

RADAR_LABELS: dict[str, str] = {
    "avg_watch_per_active_day": (
        "So viele Videos siehst du <br>pro Tag wenn du TikTok öffnest"
    ),
    "avg_active_hours_per_day": "Zeit die du auf TikTok pro Tag verbringst",
    "weekend_activity_frac": (
        "So viel deiner TikTok-Zeit <br>findet am Wochenende statt"
    ),
    "night_activity_frac": "So viel deiner TikTok-Zeit <br>findet nachts statt",
    "peak_activity_hour": "Wann scrollst du am aktivsten?",
}

METRIC_LABELS: dict[str, str] = {
    "avg_watch_per_active_day": "Ø angesehene Videos pro aktivem Tag",
    "avg_active_hours_per_day": "Ø aktive Stunden pro Tag",
    "weekend_activity_frac": "Anteil Wochenend-Wiedergaben",
    "night_activity_frac": "Anteil Nacht-Wiedergaben (22-6 Uhr)",
    "peak_activity_hour": "Stoßzeit (Stunde)",
}

FRACTION_METRICS = {
    "weekend_activity_frac",
    "night_activity_frac",
}


def _behaviour_csv_path() -> Path:
    configured = getattr(settings, "BEHAVIOUR_METRICS_CSV_PATH", "") or ""
    if configured:
        return Path(configured)
    return _DEFAULT_BEHAVIOUR_METRICS_CSV


def _parse_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    if math.isnan(parsed):
        return None
    return parsed


def _filtered_watch_history(
    data: TikTokUserData,
) -> list[WatchHistoryRecord]:
    return [
        record
        for record in data.watch_history or []
        if isinstance(record.get("date"), datetime)
        and record["date"] >= REPORT_FIRST_DATE_TO_INCLUDE
    ]


def _percentile_rank(value: float, sorted_values: list[float]) -> float:
    if not sorted_values:
        return 0.0
    below = sum(1 for v in sorted_values if v < value)
    equal = sum(1 for v in sorted_values if v == value)
    return 100.0 * (below + 0.5 * equal) / len(sorted_values)


def _quantile(sorted_values: list[float], p: float) -> float:
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    idx = p * (n - 1)
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return sorted_values[lo]
    weight = idx - lo
    return sorted_values[lo] * (1 - weight) + sorted_values[hi] * weight


def _distribution_stats(sorted_values: list[float]) -> dict[str, float]:
    n = len(sorted_values)

    return {
        "min": sorted_values[0],
        "max": sorted_values[-1],
        "mean": sum(sorted_values) / n,
        "median": _quantile(sorted_values, 0.5),
        "p25": _quantile(sorted_values, 0.25),
        "p75": _quantile(sorted_values, 0.75),
    }


def trimmed_reference_distribution(
    sorted_values: list[float],
    *,
    lower_percentile: float = 0.01,
    upper_percentile: float = 0.99,
) -> tuple[list[float], float, float]:
    """Trim reference extremes for violin plots; return values and bounds."""
    if not sorted_values:
        return [], 0.0, 0.0
    lower_bound = _quantile(sorted_values, lower_percentile)
    upper_bound = _quantile(sorted_values, upper_percentile)
    trimmed = [v for v in sorted_values if lower_bound <= v <= upper_bound]
    return trimmed, lower_bound, upper_bound


def _format_metric_value(metric: str, value: float) -> str:
    if metric in FRACTION_METRICS:
        return f"{value * 100:.1f}\u00a0%"
    if metric == "peak_activity_hour":
        return f"{round(value)}:00"
    return f"{value:.2f}"


@lru_cache(maxsize=1)
def _load_reference_distributions() -> dict[str, list[float]]:
    """Reference population distributions per metric (CSV used for comparison only)."""
    path = _behaviour_csv_path()
    if not path.is_file():
        return {}

    values_by_metric: dict[str, list[float]] = defaultdict(list)
    with path.open("r", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            for key, raw in row.items():
                if key == "participant_id":
                    continue
                val = _parse_float(raw)
                if val is not None:
                    values_by_metric[key].append(val)

    return {key: sorted(values) for key, values in values_by_metric.items()}


def compute_watch_history_metrics(data: TikTokUserData) -> dict[str, float]:
    """Compute behaviour metrics from donated watch history only."""
    watches = _filtered_watch_history(data)
    watch_count = len(watches)

    if watch_count == 0:
        return {}

    daily_watches: dict[date, int] = defaultdict(int)
    daily_hours: dict[date, set[int]] = defaultdict(set)
    hour_counts: dict[int, int] = defaultdict(int)
    weekend_watches = 0
    weekday_watches = 0
    night_watches = 0

    for record in watches:
        ts = record["date"]
        assert isinstance(ts, datetime)
        day = ts.date()
        daily_watches[day] += 1
        daily_hours[day].add(ts.hour)
        hour_counts[ts.hour] += 1
        if ts.weekday() >= _SATURDAY_WEEKDAY:
            weekend_watches += 1
        else:
            weekday_watches += 1
        if ts.hour >= _NIGHT_HOUR_START or ts.hour < _NIGHT_HOUR_END:
            night_watches += 1

    active_days = len(daily_watches)
    active_hours_per_day = [len(hours) for hours in daily_hours.values()]
    peak_hour = max(hour_counts, key=hour_counts.get)

    return {
        "total_watches": float(watch_count),
        "active_days": float(active_days),
        "active_weeks": float(len({day.isocalendar()[:2] for day in daily_watches})),
        "avg_watch_per_active_day": watch_count / active_days,
        "avg_active_hours_per_day": sum(active_hours_per_day)
        / len(active_hours_per_day),
        "weekend_activity_frac": weekend_watches / (weekend_watches + weekday_watches),
        "night_activity_frac": night_watches / watch_count,
        "peak_activity_hour": float(peak_hour),
    }


def compute_behaviour_comparisons(
    data: TikTokUserData,
) -> list[BehaviourComparisonRecord]:
    """Compare watch-history profile metrics to the reference population."""
    participant_metrics = compute_watch_history_metrics(data)
    if not participant_metrics:
        return []

    reference_values = _load_reference_distributions()
    if not reference_values:
        return []

    comparisons: list[BehaviourComparisonRecord] = []
    for metric in PROFILE_METRICS:
        value = participant_metrics.get(metric)
        if value is None or math.isnan(value):
            continue
        population = reference_values.get(metric)
        if not population:
            continue
        percentile = _percentile_rank(value, population)
        stats = _distribution_stats(population)
        ref_mean = stats["mean"]
        mean_percentile = _percentile_rank(ref_mean, population)
        comparisons.append(
            {
                "metric": metric,
                "label": METRIC_LABELS[metric],
                "radar_label": RADAR_LABELS[metric],
                "value": value,
                "value_display": _format_metric_value(metric, value),
                "percentile": percentile,
                "reference_mean": ref_mean,
                "reference_mean_display": _format_metric_value(metric, ref_mean),
                "reference_mean_percentile": mean_percentile,
                "reference_median": stats["median"],
                "reference_median_display": _format_metric_value(
                    metric, stats["median"]
                ),
                "reference_p25": stats["p25"],
                "reference_p75": stats["p75"],
                "radar_user": percentile,
                "radar_mean": mean_percentile,
                "is_fraction": metric in FRACTION_METRICS,
            }
        )
    return comparisons


def clear_behaviour_reference_cache() -> None:
    _load_reference_distributions.cache_clear()


def get_profile_reference_distributions() -> dict[str, list[float]]:
    """Reference population values for profile metrics (violin plots, etc.)."""
    reference_values = _load_reference_distributions()
    return {
        metric: reference_values[metric]
        for metric in PROFILE_METRICS
        if metric in reference_values
    }
