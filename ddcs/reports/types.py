from typing import TypedDict


class PartyCountRecord(TypedDict):
    party: str
    count: int


class DailyPartyCountRecord(TypedDict):
    date: str
    party: str
    count: int


class TopVideoRecord(TypedDict):
    video_id: int
    username: str
    party: str | None
    view_count: int
    description: str


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
    radar_user: float
    radar_mean: float
    is_fraction: bool


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
