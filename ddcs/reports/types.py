from typing import NotRequired, TypedDict


class PartyCountRecord(TypedDict):
    party: str
    count: int


class DailyPartyCountRecord(TypedDict):
    date: str
    party: str
    count: int


class DailyAccountPostCountRecord(TypedDict):
    """One (account, date) entry in the public report's base dataset.

    ``count`` is ``None`` when the account had no successful sync for that
    date (see ``SyncAttempt``), i.e. coverage is unknown rather than a
    confirmed zero posts.
    """

    username: str
    party: str
    date: str
    count: int | None


class TopVideoRecord(TypedDict):
    video_id: int
    username: str
    party: str | None
    # How often this video appears in the participant's watch history.
    view_count: int
    description: str
    # Share of this participant's political watches that were this video.
    watch_share: float
    # Mean inferred dwell time (sec) across occurrences; None if unknown.
    avg_watch_sec: float | None
    # TikTok Research API total view count; used for viral ranking.
    total_views: int | None
    liked: bool
    shared: bool
    saved: bool
    followed_author: bool
    tiktok_url: NotRequired[str]
    embed_url: NotRequired[str]


class BehaviourComparisonRecord(TypedDict):
    metric: str
    label: str
    radar_label: str
    value: float
    value_display: str
    percentile: float
    reference_mean: float
    reference_mean_display: str
    reference_mean_percentile: float
    reference_median: float
    reference_median_display: str
    reference_p25: float
    reference_p75: float
    reference_min: float
    reference_max: float
    reference_min_display: str
    reference_max_display: str
    radar_user: float
    radar_mean: float
    is_fraction: bool
    chart_user_value: NotRequired[float]
    chart_reference_value: NotRequired[float]
    chart_user_value_display: NotRequired[str]
    chart_reference_value_display: NotRequired[str]
    # Mean videos watched at each clock hour (0..23) across the donation window.
    hourly_watch_means: NotRequired[list[float]]
    reference_hourly_watch_means: NotRequired[list[float]]
    # Mean active hours for Mon..Sun (Python weekday order).
    weekday_active_hours: NotRequired[list[float]]
    reference_weekday_active_hours: NotRequired[list[float]]


class ReportStatistics(TypedDict):
    """Shape returned by ``compute_report_statistics`` and accepted by
    ``ParticipantReportStatistics(**stats)``. The keys mirror the model's
    JSON fields one-to-one."""

    videos_seen_count_total: int

    seen_pol_video_ids: list[int]
    liked_pol_video_ids: list[int]
    followed_pol_users: list[str]

    party_counts: list[PartyCountRecord]
    daily_party_counts: list[DailyPartyCountRecord]
    hashtags_by_pol_video: dict[int, str]
    top_videos: list[TopVideoRecord]

    party_hashtags: list[str]
    non_party_hashtags: list[str]

    behaviour_comparisons: list[BehaviourComparisonRecord]
