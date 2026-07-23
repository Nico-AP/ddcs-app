"""Behaviour metrics from donated watch history, compared to a reference population."""

import csv
import math
from collections import defaultdict
from datetime import date, datetime
from functools import lru_cache
from itertools import pairwise
from random import choice
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
    "peak_activity_hour",
    "frac_instant_skip",
    "rate_like",
    "frac_political_engagement",
]

# Subset shown as behaviour comparison bars in the report (display order).
BEHAVIOUR_CHART_METRICS: list[str] = [
    "avg_active_hours_per_day",
    "avg_videos_per_session",
    "avg_session_length_sec",
    "frac_instant_skip",
    "rate_like",
    "frac_political_engagement",
    "peak_activity_hour",
    "night_activity_frac",
    "weekday_active_hours",
    "weekend_activity_frac",
]

# Metrics grouped into carousel slides (each inner list = one slide).
BEHAVIOUR_CHART_SLIDES: list[list[str]] = [
    [
        "avg_active_hours_per_day",
        "avg_videos_per_session",
        "avg_session_length_sec",
    ],
    [
        "frac_instant_skip",
        "rate_like",
        "frac_political_engagement",
    ],
    [
        "peak_activity_hour",
        "night_activity_frac",
    ],
    [
        "weekday_active_hours",
        "weekend_activity_frac",
    ],
]

RADAR_LABELS: dict[str, str] = {
    "avg_session_length_sec": "Durchschnittliche <br>Session-Länge (Min.)",
    "avg_videos_per_session": ("Durchschnittliche Anzahl <br>Videos pro Session"),
    "avg_active_hours_per_day": "Durchschnittliche Anzahl <br>aktiver Stunden pro Tag",
    "weekend_activity_frac": ("Anteil TikTok-Zeit am Wochenende"),
    "night_activity_frac": "Anteil TikTok-Zeit nachts",
    "peak_activity_hour": "Aktivste Nutzungsstunde",
    "weekday_active_hours": "Aktive Stunden nach Wochentag",
    "frac_instant_skip": ("Anteil Instant-Skips"),
    "rate_like": "Anteil gelikter Videos",
    "frac_political_engagement": ("Anteil politische Interaktionen"),
}

METRIC_LABELS: dict[str, str] = {
    "avg_session_length_sec": "Ø Session-Länge (Min.)",
    "avg_videos_per_session": "Ø Videos pro Session",
    "avg_active_hours_per_day": "Ø aktive Stunden pro Tag",
    "weekend_activity_frac": "Anteil Wochenend-Wiedergaben",
    "night_activity_frac": "Anteil Nacht-Wiedergaben (22-6 Uhr)",
    "peak_activity_hour": "Aktivste Nutzungsstunde",
    "weekday_active_hours": "Ø aktive Stunden nach Wochentag",
    "frac_instant_skip": "Anteil Instant-Skips (< 1 Sek. bis zum nächsten Video)",
    "rate_like": "Anteil gelikter Videos (Likes pro Ansicht)",
    "frac_political_engagement": "Anteil politische Interaktionen",
}

FRACTION_METRICS = {
    "weekend_activity_frac",
    "night_activity_frac",
    "frac_instant_skip",
    "rate_like",
    "frac_political_engagement",
}

_WEEKDAY_ACTIVE_HOURS_CSV_KEYS = (
    "avg_active_hours_mon",
    "avg_active_hours_tue",
    "avg_active_hours_wed",
    "avg_active_hours_thu",
    "avg_active_hours_fri",
    "avg_active_hours_sat",
    "avg_active_hours_sun",
)
_HOURS_PER_DAY = 24
_WEEKDAYS_PER_WEEK = 7

AgeGroup = Literal["all", "under30", "over30"]
GenderFilter = Literal["any", "male", "female"]
VALID_AGE_GROUPS = frozenset({"all", "under30", "over30"})
VALID_GENDERS = frozenset({"any", "male", "female"})
_AGE_THRESHOLD = 30


class ReferenceParticipantRow(TypedDict):
    gender: str
    age: float | None
    metrics: dict[str, float]
    hourly_watch_means: list[float]
    weekday_active_hours: list[float]


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


def _hourly_watch_means(watches: list[WatchHistoryRecord]) -> list[float]:
    """Mean videos watched at each clock hour across the donation date span."""
    if not watches:
        return [0.0] * _HOURS_PER_DAY

    hour_counts: dict[int, int] = defaultdict(int)
    days: set[date] = set()
    for record in watches:
        ts = record["date"]
        assert isinstance(ts, datetime)
        hour_counts[ts.hour] += 1
        days.add(ts.date())

    n_days = (max(days) - min(days)).days + 1
    return [hour_counts.get(hour, 0) / n_days for hour in range(_HOURS_PER_DAY)]


def _weekday_active_hours(watches: list[WatchHistoryRecord]) -> list[float]:
    """Mean distinct active hours for each weekday (Mon=0 .. Sun=6)."""
    if not watches:
        return [0.0] * _WEEKDAYS_PER_WEEK

    daily_hours: dict[date, set[int]] = defaultdict(set)
    for record in watches:
        ts = record["date"]
        assert isinstance(ts, datetime)
        daily_hours[ts.date()].add(ts.hour)

    hours_by_weekday: dict[int, list[int]] = defaultdict(list)
    for day, hours in daily_hours.items():
        hours_by_weekday[day.weekday()].append(len(hours))

    return [
        (
            sum(hours_by_weekday[weekday]) / len(hours_by_weekday[weekday])
            if hours_by_weekday[weekday]
            else 0.0
        )
        for weekday in range(_WEEKDAYS_PER_WEEK)
    ]


def _reference_row_hourly_watch_means(row: dict[str, str | None]) -> list[float]:
    hourly: list[float] = []
    for hour in range(_HOURS_PER_DAY):
        value = _parse_float(row.get(f"avg_watches_hour_{hour:02d}"))
        hourly.append(value if value is not None else 0.0)
    return hourly


def _reference_row_weekday_active_hours(row: dict[str, str | None]) -> list[float]:
    weekday_hours: list[float] = []
    for key in _WEEKDAY_ACTIVE_HOURS_CSV_KEYS:
        value = _parse_float(row.get(key))
        weekday_hours.append(value if value is not None else 0.0)
    return weekday_hours


def _mean_series(
    series_list: list[list[float]],
    length: int,
) -> list[float]:
    if not series_list:
        return [0.0] * length
    return [
        sum(series[index] for series in series_list) / len(series_list)
        for index in range(length)
    ]


def _mean_hourly_watch_means(
    participants: list[ReferenceParticipantRow] | tuple[ReferenceParticipantRow, ...],
) -> list[float]:
    return _mean_series([p["hourly_watch_means"] for p in participants], _HOURS_PER_DAY)


def _mean_weekday_active_hours(
    participants: list[ReferenceParticipantRow] | tuple[ReferenceParticipantRow, ...],
) -> list[float]:
    return _mean_series(
        [p["weekday_active_hours"] for p in participants],
        _WEEKDAYS_PER_WEEK,
    )


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


def avg_inferred_watch_sec_by_video(
    watches: list[WatchHistoryRecord],
) -> dict[int, float]:
    """Mean inferred dwell time (seconds) per video from gaps to the next watch.

    Donated watch history has no true watch duration — only event timestamps.
    For each consecutive pair in the sorted history, the gap is attributed to
    the earlier video when it falls within a session (≤ ``_SESSION_BREAK_SEC``).
    The last video of a session has no measurable gap and is skipped.
    """
    dated: list[tuple[datetime, int]] = []
    for record in watches:
        ts = record.get("date")
        video_id = record.get("video_id")
        if not isinstance(ts, datetime) or video_id is None:
            continue
        if ts < REPORT_FIRST_DATE_TO_INCLUDE:
            continue
        dated.append((ts, video_id))
    if len(dated) < _MIN_WATCH_EVENTS_FOR_GAP:
        return {}

    dated.sort(key=lambda item: item[0])
    gaps_by_video: dict[int, list[float]] = defaultdict(list)
    for (prev_ts, prev_id), (next_ts, _next_id) in pairwise(dated):
        gap = (next_ts - prev_ts).total_seconds()
        if 0 <= gap <= _SESSION_BREAK_SEC:
            gaps_by_video[prev_id].append(gap)

    return {
        video_id: sum(gaps) / len(gaps)
        for video_id, gaps in gaps_by_video.items()
        if gaps
    }


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
                    "hourly_watch_means": _reference_row_hourly_watch_means(row),
                    "weekday_active_hours": _reference_row_weekday_active_hours(row),
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


def _reference_hourly_watch_means_for_filter(
    age_group: AgeGroup = "all",
    gender: GenderFilter = "any",
) -> list[float]:
    participants = [
        participant
        for participant in _load_reference_participants()
        if _matches_demographic_filter(participant, age_group, gender)
    ]
    return _mean_hourly_watch_means(participants)


def _reference_weekday_active_hours_for_filter(
    age_group: AgeGroup = "all",
    gender: GenderFilter = "any",
) -> list[float]:
    participants = [
        participant
        for participant in _load_reference_participants()
        if _matches_demographic_filter(participant, age_group, gender)
    ]
    return _mean_weekday_active_hours(participants)


def sample_reference_activity_profile() -> (
    tuple[list[float], float, list[float]] | None
):
    """Sample one CSV participant's hourly + weekday curves for synthetic previews."""
    participants = _load_reference_participants()
    if not participants:
        return None

    participant = choice(participants)  # noqa: S311
    hourly = list(participant["hourly_watch_means"])
    weekday_hours = list(participant["weekday_active_hours"])
    peak = participant["metrics"].get("peak_activity_hour")
    if peak is None:
        peak = float(max(range(_HOURS_PER_DAY), key=lambda hour: hourly[hour]))
    return hourly, float(peak), weekday_hours


def apply_sampled_reference_activity_profiles(
    comparisons: list[BehaviourComparisonRecord],
) -> list[BehaviourComparisonRecord]:
    """Replace synthetic ridge curves with one real CSV participant sample."""
    sampled = sample_reference_activity_profile()
    if sampled is None:
        return comparisons

    hourly, peak, weekday_hours = sampled
    population = _load_reference_distributions().get("peak_activity_hour")
    updated: list[BehaviourComparisonRecord] = []
    for row in comparisons:
        if row["metric"] == "peak_activity_hour" and population:
            updated.append(
                _build_peak_hour_comparison(
                    peak,
                    population,
                    hourly_watch_means=hourly,
                    reference_hourly_watch_means=row.get(
                        "reference_hourly_watch_means"
                    ),
                )
            )
            continue
        if row["metric"] == "weekday_active_hours":
            updated.append(
                _build_weekday_active_hours_comparison(
                    weekday_hours,
                    row.get("reference_weekday_active_hours")
                    or [0.0] * _WEEKDAYS_PER_WEEK,
                )
            )
            continue
        updated.append(row)
    return updated


# Backwards-compatible aliases used by older call sites/tests.
def sample_reference_hourly_profile() -> tuple[list[float], float] | None:
    sampled = sample_reference_activity_profile()
    if sampled is None:
        return None
    hourly, peak, _weekday = sampled
    return hourly, peak


def apply_sampled_reference_hourly_profile(
    comparisons: list[BehaviourComparisonRecord],
) -> list[BehaviourComparisonRecord]:
    return apply_sampled_reference_activity_profiles(comparisons)


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
    like_count = len(_filtered_engagement_records(data.liked_videos))

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
        "rate_like": like_count / watch_count,
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


def _peak_hour_same_fraction(peak_hour: int, population: list[float]) -> float:
    if not population:
        return 0.0
    matches = sum(1 for value in population if round(value) == peak_hour)
    return matches / len(population)


def _build_peak_hour_comparison(
    peak_hour: float,
    population: list[float],
    *,
    hourly_watch_means: list[float] | None = None,
    reference_hourly_watch_means: list[float] | None = None,
) -> BehaviourComparisonRecord:
    hour = round(peak_hour)
    same_frac = _peak_hour_same_fraction(hour, population)
    diff_frac = 1.0 - same_frac
    stats = _distribution_stats(population)
    same_display = f"{same_frac * 100:.1f}\u00a0%"
    diff_display = f"{diff_frac * 100:.1f}\u00a0%"
    row: BehaviourComparisonRecord = {
        "metric": "peak_activity_hour",
        "label": METRIC_LABELS["peak_activity_hour"],
        "radar_label": RADAR_LABELS["peak_activity_hour"],
        "value": peak_hour,
        "value_display": _format_metric_value("peak_activity_hour", peak_hour),
        "percentile": same_frac * 100.0,
        "reference_mean": diff_frac,
        "reference_mean_display": diff_display,
        "reference_mean_percentile": 50.0,
        "reference_median": stats["median"],
        "reference_median_display": _format_metric_value(
            "peak_activity_hour", stats["median"]
        ),
        "reference_p25": stats["p25"],
        "reference_p75": stats["p75"],
        "reference_min": stats["min"],
        "reference_max": stats["max"],
        "reference_min_display": _format_metric_value(
            "peak_activity_hour", stats["min"]
        ),
        "reference_max_display": _format_metric_value(
            "peak_activity_hour", stats["max"]
        ),
        "radar_user": same_frac * 100.0,
        "radar_mean": 50.0,
        "is_fraction": False,
        "chart_user_value": same_frac,
        "chart_reference_value": diff_frac,
        "chart_user_value_display": same_display,
        "chart_reference_value_display": diff_display,
    }
    if hourly_watch_means is not None:
        row["hourly_watch_means"] = hourly_watch_means
    if reference_hourly_watch_means is not None:
        row["reference_hourly_watch_means"] = reference_hourly_watch_means
    return row


def _build_weekday_active_hours_comparison(
    weekday_active_hours: list[float],
    reference_weekday_active_hours: list[float],
) -> BehaviourComparisonRecord:
    user_vals = weekday_active_hours or [0.0] * _WEEKDAYS_PER_WEEK
    ref_vals = reference_weekday_active_hours or [0.0] * _WEEKDAYS_PER_WEEK
    user_mean = sum(user_vals) / len(user_vals)
    ref_mean = sum(ref_vals) / len(ref_vals)
    return {
        "metric": "weekday_active_hours",
        "label": METRIC_LABELS["weekday_active_hours"],
        "radar_label": RADAR_LABELS["weekday_active_hours"],
        "value": user_mean,
        "value_display": _format_metric_value("avg_active_hours_per_day", user_mean),
        "percentile": 50.0,
        "reference_mean": ref_mean,
        "reference_mean_display": _format_metric_value(
            "avg_active_hours_per_day", ref_mean
        ),
        "reference_mean_percentile": 50.0,
        "reference_median": ref_mean,
        "reference_median_display": _format_metric_value(
            "avg_active_hours_per_day", ref_mean
        ),
        "reference_p25": min(ref_vals),
        "reference_p75": max(ref_vals),
        "reference_min": min(ref_vals),
        "reference_max": max(ref_vals),
        "reference_min_display": _format_metric_value(
            "avg_active_hours_per_day", min(ref_vals)
        ),
        "reference_max_display": _format_metric_value(
            "avg_active_hours_per_day", max(ref_vals)
        ),
        "radar_user": 50.0,
        "radar_mean": 50.0,
        "is_fraction": False,
        "weekday_active_hours": user_vals,
        "reference_weekday_active_hours": ref_vals,
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
    reference_hourly_means = _reference_hourly_watch_means_for_filter(age_group, gender)
    reference_weekday_means = _reference_weekday_active_hours_for_filter(
        age_group, gender
    )
    for row in comparisons:
        if row["metric"] == "weekday_active_hours":
            user_weekdays = row.get("weekday_active_hours")
            if not user_weekdays or len(user_weekdays) != _WEEKDAYS_PER_WEEK:
                updated.append(row)
                continue
            updated.append(
                _build_weekday_active_hours_comparison(
                    user_weekdays,
                    reference_weekday_means,
                )
            )
            continue
        population = reference_values.get(row["metric"])
        if not population:
            updated.append(row)
            continue
        if row["metric"] == "peak_activity_hour":
            updated.append(
                _build_peak_hour_comparison(
                    row["value"],
                    population,
                    hourly_watch_means=row.get("hourly_watch_means"),
                    reference_hourly_watch_means=reference_hourly_means,
                )
            )
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
    watches = _filtered_watch_history(data)
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

    hourly_means = _hourly_watch_means(watches)
    reference_hourly_means = _reference_hourly_watch_means_for_filter()
    weekday_means = _weekday_active_hours(watches)
    reference_weekday_means = _reference_weekday_active_hours_for_filter()
    comparisons: list[BehaviourComparisonRecord] = []
    for metric in PROFILE_METRICS:
        value = participant_metrics.get(metric)
        if value is None or math.isnan(value):
            continue
        population = reference_values.get(metric)
        if not population:
            continue
        if metric == "peak_activity_hour":
            comparisons.append(
                _build_peak_hour_comparison(
                    value,
                    population,
                    hourly_watch_means=hourly_means,
                    reference_hourly_watch_means=reference_hourly_means,
                )
            )
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

    comparisons.append(
        _build_weekday_active_hours_comparison(
            weekday_means,
            reference_weekday_means,
        )
    )
    return comparisons


def clear_behaviour_reference_cache() -> None:
    _load_reference_participants.cache_clear()
    _load_reference_distributions.cache_clear()
