"""Behaviour metrics from donated watch history, compared to a reference population."""

import csv
import math
from collections import defaultdict
from datetime import date, datetime
from functools import lru_cache
from itertools import pairwise

from ddcs.core.types import TikTokUserData, WatchHistoryRecord
from ddcs.reports.config import BEHAVIOUR_METRICS_CSV_PATH, REPORT_FIRST_DATE_TO_INCLUDE
from ddcs.reports.types import BehaviourComparisonRecord

_SATURDAY_WEEKDAY = 5
_NIGHT_HOUR_START = 22
_NIGHT_HOUR_END = 6
_INSTANT_SKIP_MAX_GAP_SEC = 1
_MIN_WATCH_EVENTS_FOR_GAP = 2

# Profile metrics shown in the report (totals omitted from the UI).
PROFILE_METRICS: list[str] = [
    "avg_watch_per_active_day",
    "avg_active_hours_per_day",
    "weekend_activity_frac",
    "night_activity_frac",
    "frac_instant_skip",
    "peak_activity_hour",
]

RADAR_LABELS: dict[str, str] = {
    "avg_watch_per_active_day": (
        "Durchschnittliche Anzahl <br>angesehene Videos pro aktivem Tag"
    ),
    "avg_active_hours_per_day": "Durchschnittliche Anzahl <br>aktiver Stunden pro Tag",
    "weekend_activity_frac": ("Anteil TikTok-Zeit am Wochenende"),
    "night_activity_frac": "Anteil TikTok-Zeit nachts",
    "frac_instant_skip": ("Anteil Instant-Skips"),
    "peak_activity_hour": "Deine TikTok-Tageszeit",
}

METRIC_LABELS: dict[str, str] = {
    "avg_watch_per_active_day": "Ø angesehene Videos pro aktivem Tag",
    "avg_active_hours_per_day": "Ø aktive Stunden pro Tag",
    "weekend_activity_frac": "Anteil Wochenend-Wiedergaben",
    "night_activity_frac": "Anteil Nacht-Wiedergaben (22-6 Uhr)",
    "frac_instant_skip": "Anteil Instant-Skips (< 1 Sek. bis zum nächsten Video)",
    "peak_activity_hour": "Tageszeit wo du auf TikTok am aktivsten bist (Stunde)",
}

FRACTION_METRICS = {
    "weekend_activity_frac",
    "night_activity_frac",
    "frac_instant_skip",
}


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


def _format_metric_value(metric: str, value: float) -> str:
    if metric in FRACTION_METRICS:
        return f"{value * 100:.1f}\u00a0%"
    if metric == "peak_activity_hour":
        return f"{round(value)}:00"
    return f"{value:.2f}"


def _frac_instant_skip(timestamps: list[datetime]) -> float:
    """Share of views scrolled away within one second (gap to next watch event)."""
    if len(timestamps) < _MIN_WATCH_EVENTS_FOR_GAP:
        return 0.0
    sorted_ts = sorted(timestamps)
    instant_skips = sum(
        1
        for prev, nxt in pairwise(sorted_ts)
        if (nxt - prev).total_seconds() < _INSTANT_SKIP_MAX_GAP_SEC
    )
    return instant_skips / (len(sorted_ts) - 1)


@lru_cache(maxsize=1)
def _load_reference_distributions() -> dict[str, list[float]]:
    """Reference population distributions per metric (CSV used for comparison only)."""
    path = BEHAVIOUR_METRICS_CSV_PATH
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
    timestamps: list[datetime] = []
    weekend_watches = 0
    weekday_watches = 0
    night_watches = 0

    for record in watches:
        ts = record["date"]
        assert isinstance(ts, datetime)
        timestamps.append(ts)
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
        "frac_instant_skip": _frac_instant_skip(timestamps),
        "peak_activity_hour": float(peak_hour),
    }


# TODO: Maybe revise; mixes computation/stats logic with matters purely
#  related to presentation. Presentation-related parts (labels, value formatting)
#  could be moved to plots for consistency.
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
