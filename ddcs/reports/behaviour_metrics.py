"""Behaviour metrics from donated watch history, compared to a reference population."""

import csv
import math
from collections import defaultdict
from datetime import date, datetime
from functools import lru_cache
from itertools import pairwise
from typing import Literal, TypedDict

from ddcs.core.types import LikedVideoRecord, TikTokUserData, WatchHistoryRecord
from ddcs.reports.config import BEHAVIOUR_METRICS_CSV_PATH, REPORT_FIRST_DATE_TO_INCLUDE
from ddcs.reports.types import BehaviourComparisonRecord

_SATURDAY_WEEKDAY = 5
_NIGHT_HOUR_START = 22
_NIGHT_HOUR_END = 6
_INSTANT_SKIP_MAX_GAP_SEC = 1
_SESSION_BREAK_SEC = 90
_MIN_WATCH_EVENTS_FOR_GAP = 2

# Profile metrics computed for each participant (incl. data merged into chart copy).
PROFILE_METRICS: list[str] = [
    "avg_active_hours_per_day",
    "avg_videos_per_session",
    "avg_session_length_sec",
    "weekend_activity_frac",
    "night_activity_frac",
    "frac_instant_skip",
    "frac_political_engagement",
]

# Subset shown as behaviour comparison bars in the report (display order).
BEHAVIOUR_CHART_METRICS: list[str] = [
    "avg_active_hours_per_day",
    "avg_videos_per_session",
    "avg_session_length_sec",
    "weekend_activity_frac",
    "night_activity_frac",
    "frac_instant_skip",
    "frac_political_engagement",
]

# Metrics grouped into carousel slides (each inner list = one slide).
BEHAVIOUR_CHART_SLIDES: list[list[str]] = [
    [
        "avg_active_hours_per_day",
        "avg_videos_per_session",
        "avg_session_length_sec",
    ],
    [
        "weekend_activity_frac",
        "night_activity_frac",
    ],
    [
        "frac_instant_skip",
        "frac_political_engagement",
    ],
]

RADAR_LABELS: dict[str, str] = {
    "avg_session_length_sec": "Durchschnittliche <br>Session-Länge (Min.)",
    "avg_videos_per_session": ("Durchschnittliche Anzahl <br>Videos pro Session"),
    "avg_active_hours_per_day": "Durchschnittliche Anzahl <br>aktiver Stunden pro Tag",
    "weekend_activity_frac": ("Anteil TikTok-Zeit am Wochenende"),
    "night_activity_frac": "Anteil TikTok-Zeit nachts",
    "frac_instant_skip": ("Anteil Instant-Skips"),
    "frac_political_engagement": ("Anteil politische Interaktionen"),
}

METRIC_LABELS: dict[str, str] = {
    "avg_session_length_sec": "Ø Session-Länge (Min.)",
    "avg_videos_per_session": "Ø Videos pro Session",
    "avg_active_hours_per_day": "Ø aktive Stunden pro Tag",
    "weekend_activity_frac": "Anteil Wochenend-Wiedergaben",
    "night_activity_frac": "Anteil Nacht-Wiedergaben (22-6 Uhr)",
    "frac_instant_skip": "Anteil Instant-Skips (< 1 Sek. bis zum nächsten Video)",
    "frac_political_engagement": "Anteil politische Interaktionen",
}

FRACTION_METRICS = {
    "weekend_activity_frac",
    "night_activity_frac",
    "frac_instant_skip",
    "frac_political_engagement",
}

AgeGroup = Literal["all", "under30", "over30"]
GenderFilter = Literal["any", "male", "female"]
VALID_AGE_GROUPS = frozenset({"all", "under30", "over30"})
VALID_GENDERS = frozenset({"any", "male", "female"})
_AGE_THRESHOLD = 30


class ReferenceParticipantRow(TypedDict):
    gender: str
    age: float | None
    metrics: dict[str, float]


class ReferenceDemographicFilter(TypedDict):
    age_group: AgeGroup
    gender: GenderFilter


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


def _filtered_engagement_records(
    records: list[LikedVideoRecord] | None,
) -> list[LikedVideoRecord]:
    return [
        record
        for record in records or []
        if isinstance(record.get("date"), datetime)
        and record["date"] >= REPORT_FIRST_DATE_TO_INCLUDE
        and record.get("video_id") is not None
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
    if metric == "avg_session_length_sec":
        return f"{value / 60:.1f}\u00a0Min."
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


def _watch_sessions(timestamps: list[datetime]) -> list[tuple[float, int]]:
    """Return (duration_sec, video_count) per consecutive watch session."""
    if not timestamps:
        return []
    sorted_ts = sorted(timestamps)
    sessions: list[list[datetime]] = [[sorted_ts[0]]]
    for prev, curr in pairwise(sorted_ts):
        if (curr - prev).total_seconds() > _SESSION_BREAK_SEC:
            sessions.append([curr])
        else:
            sessions[-1].append(curr)
    return [
        ((session[-1] - session[0]).total_seconds(), len(session))
        for session in sessions
    ]


@lru_cache(maxsize=1)
def _load_reference_participants() -> tuple[ReferenceParticipantRow, ...]:
    """Reference participants with demographics and profile metrics from CSV."""
    path = BEHAVIOUR_METRICS_CSV_PATH
    if not path.is_file():
        return ()

    participants: list[ReferenceParticipantRow] = []
    with path.open("r", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            metrics: dict[str, float] = {}
            for metric in PROFILE_METRICS:
                val = _parse_float(row.get(metric))
                if val is not None:
                    metrics[metric] = val
            if not metrics:
                continue
            participants.append(
                {
                    "gender": (row.get("gender") or "").strip(),
                    "age": _parse_float(row.get("age")),
                    "metrics": metrics,
                }
            )
    return tuple(participants)


def normalize_age_group(value: str | None) -> AgeGroup:
    if value in VALID_AGE_GROUPS:
        return value  # type: ignore[return-value]
    return "all"


def normalize_gender_filter(value: str | None) -> GenderFilter:
    if value in VALID_GENDERS:
        return value  # type: ignore[return-value]
    return "any"


def _matches_demographic_filter(
    participant: ReferenceParticipantRow,
    age_group: AgeGroup,
    gender: GenderFilter,
) -> bool:
    if gender != "any":
        csv_gender = participant["gender"].lower()
        if gender == "male" and csv_gender != "male":
            return False
        if gender == "female" and csv_gender != "female":
            return False
    if age_group == "all":
        return True
    age = participant["age"]
    if age is None:
        return False
    if age_group == "under30":
        return age < _AGE_THRESHOLD
    return age >= _AGE_THRESHOLD


def reference_group_size(
    age_group: AgeGroup = "all",
    gender: GenderFilter = "any",
) -> int:
    participants = _load_reference_participants()
    return sum(
        1
        for participant in participants
        if _matches_demographic_filter(participant, age_group, gender)
    )


def reference_group_label(
    age_group: AgeGroup = "all",
    gender: GenderFilter = "any",
) -> str:
    gender_labels = {
        "any": "Alle Geschlechter",
        "male": "Männer",
        "female": "Frauen",
    }
    age_labels = {
        "all": "alle Altersgruppen",
        "under30": "unter 30 Jahren",
        "over30": "ab 30 Jahren",
    }
    return f"{gender_labels[gender]}, {age_labels[age_group]}"


def _reference_distributions_for_filter(
    age_group: AgeGroup = "all",
    gender: GenderFilter = "any",
) -> dict[str, list[float]]:
    values_by_metric: dict[str, list[float]] = defaultdict(list)
    for participant in _load_reference_participants():
        if not _matches_demographic_filter(participant, age_group, gender):
            continue
        for metric, value in participant["metrics"].items():
            values_by_metric[metric].append(value)
    return {key: sorted(values) for key, values in values_by_metric.items()}


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
    sessions = _watch_sessions(timestamps)
    session_lengths = [duration for duration, _ in sessions]
    videos_per_session = [count for _, count in sessions]

    return {
        "total_watches": float(watch_count),
        "active_days": float(active_days),
        "active_weeks": float(len({day.isocalendar()[:2] for day in daily_watches})),
        "avg_session_length_sec": sum(session_lengths) / len(session_lengths),
        "avg_videos_per_session": sum(videos_per_session) / len(videos_per_session),
        "avg_active_hours_per_day": sum(active_hours_per_day)
        / len(active_hours_per_day),
        "weekend_activity_frac": weekend_watches / (weekend_watches + weekday_watches),
        "night_activity_frac": night_watches / watch_count,
        "frac_instant_skip": _frac_instant_skip(timestamps),
        "peak_activity_hour": float(peak_hour),
    }


def compute_engagement_metrics(
    data: TikTokUserData,
    political_video_ids: frozenset[int],
) -> dict[str, float]:
    """Share of likes, shares, saves, and comments on political videos."""
    engagement_video_ids: list[int] = []
    for records in (
        data.liked_videos,
        data.shared_videos,
        data.video_bookmarks,
        data.comments,
    ):
        engagement_video_ids.extend(
            record["video_id"] for record in _filtered_engagement_records(records)
        )

    total_engagements = len(engagement_video_ids)
    if total_engagements == 0:
        return {}

    political_engagements = sum(
        1 for video_id in engagement_video_ids if video_id in political_video_ids
    )
    return {
        "frac_political_engagement": political_engagements / total_engagements,
    }


def _comparison_with_reference_population(
    row: BehaviourComparisonRecord,
    population: list[float],
) -> BehaviourComparisonRecord:
    metric = row["metric"]
    value = row["value"]
    percentile = _percentile_rank(value, population)
    stats = _distribution_stats(population)
    ref_mean = stats["mean"]
    mean_percentile = _percentile_rank(ref_mean, population)
    return {
        **row,
        "percentile": percentile,
        "reference_mean": ref_mean,
        "reference_mean_display": _format_metric_value(metric, ref_mean),
        "reference_mean_percentile": mean_percentile,
        "reference_median": stats["median"],
        "reference_median_display": _format_metric_value(metric, stats["median"]),
        "reference_p25": stats["p25"],
        "reference_p75": stats["p75"],
        "reference_min": stats["min"],
        "reference_max": stats["max"],
        "reference_min_display": _format_metric_value(metric, stats["min"]),
        "reference_max_display": _format_metric_value(metric, stats["max"]),
        "radar_user": percentile,
        "radar_mean": mean_percentile,
    }


def apply_reference_demographic_filter(
    comparisons: list[BehaviourComparisonRecord],
    *,
    age_group: AgeGroup = "all",
    gender: GenderFilter = "any",
) -> list[BehaviourComparisonRecord]:
    """Recompute reference stats for a demographic subset; user values stay fixed."""
    if not comparisons:
        return []

    reference_values = _reference_distributions_for_filter(age_group, gender)
    if not reference_values:
        return comparisons

    updated: list[BehaviourComparisonRecord] = []
    for row in comparisons:
        population = reference_values.get(row["metric"])
        if not population:
            updated.append(row)
            continue
        updated.append(_comparison_with_reference_population(row, population))
    return updated


# TODO: Maybe revise; mixes computation/stats logic with matters purely
#  related to presentation. Presentation-related parts (labels, value formatting)
#  could be moved to plots for consistency.
def compute_behaviour_comparisons(
    data: TikTokUserData,
    political_video_ids: frozenset[int] | None = None,
) -> list[BehaviourComparisonRecord]:
    """Compare watch-history profile metrics to the reference population."""
    participant_metrics = compute_watch_history_metrics(data)
    if political_video_ids is not None:
        participant_metrics.update(
            compute_engagement_metrics(data, political_video_ids)
        )
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
                "reference_min": stats["min"],
                "reference_max": stats["max"],
                "reference_min_display": _format_metric_value(metric, stats["min"]),
                "reference_max_display": _format_metric_value(metric, stats["max"]),
                "radar_user": percentile,
                "radar_mean": mean_percentile,
                "is_fraction": metric in FRACTION_METRICS,
            }
        )
    return comparisons


def clear_behaviour_reference_cache() -> None:
    _load_reference_participants.cache_clear()
    _load_reference_distributions.cache_clear()
