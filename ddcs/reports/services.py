from collections import Counter
from collections.abc import Iterable
from datetime import datetime

from ddm.participation.models import Participant

from ddcs.core.types import (
    FollowedAccountRecord,
    LikedVideoRecord,
    TikTokUserData,
    WatchHistoryRecord,
)
from ddcs.metadata.models import TikTokVideo
from ddcs.reports.behaviour_metrics import compute_behaviour_comparisons
from ddcs.reports.config import (
    N_TOP_VIDEOS,
    NO_PARTY_KEY,
    PARTIES_ORDER,
    REPORT_FIRST_DATE_TO_INCLUDE,
)
from ddcs.reports.models import ParticipantReportStatistics
from ddcs.reports.types import (
    DailyPartyCountRecord,
    PartyCountRecord,
    ReportStatistics,
    TopVideoRecord,
)
from ddcs.reports.utils import load_account_party_mapping


def _get_video_id_list(
    data: list[WatchHistoryRecord] | list[LikedVideoRecord],
) -> list[int]:
    """Create video id list from WatchHistoryRecords or LikedVideoRecords."""
    return [
        video["video_id"]
        for video in (data or [])
        if isinstance(video.get("date"), datetime)
        if video["date"] >= REPORT_FIRST_DATE_TO_INCLUDE
        if video.get("video_id") is not None
    ]


def _get_username_list(data: list[FollowedAccountRecord]) -> list[str]:
    """Create username list from FollowedAccountRecords."""
    return [
        record["username"]
        for record in (data or [])
        if record.get("username") is not None
    ]


def _build_political_video_metadata(
    party_account_videos: Iterable,
    non_party_political_videos: Iterable,
    user_party_map: dict[str, str],
) -> tuple[dict[int, str], dict[int, str]]:
    """Return ``(video_id -> party, video_id -> username)`` for both kinds of
    political videos.

    Party-account videos map to the party from ``user_party_map``.
    Non-party political videos (matched via a monitored hashtag) map to
    ``NO_PARTY_KEY``; their hashtags feed the non-party wordcloud.
    """
    party_map: dict[int, str] = {}
    username_map: dict[int, str] = {}

    for video in party_account_videos:
        username = video.user.name
        if username in user_party_map:
            party_map[video.id_tiktok] = user_party_map[username]
            username_map[video.id_tiktok] = username

    for video in non_party_political_videos:
        party_map[video.id_tiktok] = NO_PARTY_KEY
        username_map[video.id_tiktok] = video.user.name if video.user else ""

    return party_map, username_map


_PARTY_RANK = {party: i for i, party in enumerate(PARTIES_ORDER)}
_UNKNOWN_PARTY_RANK = len(PARTIES_ORDER)


def _party_sort_key(party: str) -> tuple[int, str]:
    """Rank by PARTIES_ORDER position; unknown parties go last, alphabetically."""
    return _PARTY_RANK.get(party, _UNKNOWN_PARTY_RANK), party


def _compute_party_counts(
    seen_video_ids: list[int],
    video_party_map: dict[int, str],
) -> list[PartyCountRecord]:
    """Compute total seen video counts per party, ordered by PARTIES_ORDER."""
    counts: dict[str, int] = {}
    for video_id in seen_video_ids:
        party = video_party_map.get(video_id, NO_PARTY_KEY)
        counts[party] = counts.get(party, 0) + 1

    return [
        {"party": party, "count": counts[party]}
        for party in sorted(counts, key=_party_sort_key)
    ]


def _compute_daily_party_counts(
    watch_history: list[WatchHistoryRecord],
    video_party_map: dict[int, str],
) -> list[DailyPartyCountRecord]:
    """Compute seen video counts per day per party."""
    counts: dict[tuple[str, str], int] = {}
    for record in watch_history:
        video_id = record.get("video_id")
        date = record.get("date")
        if not isinstance(date, datetime) or video_id is None:
            continue
        day = date.date().isoformat()
        party = video_party_map.get(video_id, NO_PARTY_KEY)
        counts[(day, party)] = counts.get((day, party), 0) + 1

    return [
        {"date": day, "party": party, "count": count}
        for (day, party), count in sorted(
            counts.items(), key=lambda x: x[0][0]
        )  # sorted by date
    ]


def _get_hashtags_by_video(video_ids: list[int]) -> dict[int, list[str]]:
    """Return a map of video id_tiktok -> list of hashtag names
    for the given video IDs.
    """
    videos = TikTokVideo.objects.filter(id_tiktok__in=video_ids).prefetch_related(
        "hashtags"
    )

    return {
        video.id_tiktok: list(video.hashtags.values_list("name", flat=True))
        for video in videos
    }


def _get_top_videos(
    seen_pol_video_ids: list[int],
    video_party_map: dict[int, str],
    username_by_video: dict[int, str],
    hashtags_by_video: dict[int, list[str]],
    n: int = N_TOP_VIDEOS,
) -> list[TopVideoRecord]:
    """Build top N political videos by appearance count in watch history."""
    counts = Counter(seen_pol_video_ids)
    return [
        {
            "video_id": video_id,
            "username": username_by_video.get(video_id, ""),
            "view_count": count,
            "party": video_party_map.get(video_id),
            "hashtags": hashtags_by_video.get(video_id, []),
        }
        for video_id, count in counts.most_common(n)
    ]


def compute_user_report_statistics(data: TikTokUserData) -> ReportStatistics:
    # User activities
    seen_video_ids = _get_video_id_list(data.watch_history)
    liked_video_ids = _get_video_id_list(data.liked_videos)
    followed_user_names = _get_username_list(data.followed_accounts)

    # Political content
    account_party_mapping = load_account_party_mapping()
    political_usernames = list(account_party_mapping.keys())

    party_account_videos = list(
        TikTokVideo.objects.filter(user__name__in=political_usernames).select_related(
            "user"
        )
    )
    # TODO: May need to optimize this query when we notice a slow-down.
    non_party_political_videos = list(
        TikTokVideo.objects.filter(hashtags__monitor_api=True)
        .exclude(user__name__in=political_usernames)
        .select_related("user")
        .distinct()
    )

    video_party_map, video_username_map = _build_political_video_metadata(
        party_account_videos, non_party_political_videos, account_party_mapping
    )
    political_video_id_set = {v.id_tiktok for v in party_account_videos} | {
        v.id_tiktok for v in non_party_political_videos
    }
    political_username_set = set(political_usernames)

    # Generate data used by report
    seen_pol_video_ids = [v for v in seen_video_ids if v in political_video_id_set]
    liked_pol_video_ids = list(set(liked_video_ids) & political_video_id_set)
    followed_pol_users = list(set(followed_user_names) & political_username_set)

    party_counts = _compute_party_counts(seen_video_ids, video_party_map)
    daily_party_counts = _compute_daily_party_counts(
        data.watch_history or [], video_party_map
    )
    hashtags_by_pol_video = _get_hashtags_by_video(seen_pol_video_ids)
    top_videos = _get_top_videos(
        seen_pol_video_ids,
        video_party_map,
        video_username_map,
        hashtags_by_pol_video,
    )

    party_hashtags: list[str] = []
    non_party_hashtags: list[str] = []
    for video_id, hashtag_list in hashtags_by_pol_video.items():
        if video_party_map.get(video_id) == NO_PARTY_KEY:
            non_party_hashtags.extend(hashtag_list)
        else:
            party_hashtags.extend(hashtag_list)

    return {
        "videos_seen_count_total": len(seen_video_ids),
        "seen_pol_video_ids": seen_pol_video_ids,
        "liked_pol_video_ids": liked_pol_video_ids,
        "followed_pol_users": followed_pol_users,
        "party_counts": party_counts,
        "daily_party_counts": daily_party_counts,
        "hashtags_by_pol_video": hashtags_by_pol_video,
        "top_videos": top_videos,
        "party_hashtags": party_hashtags,
        "non_party_hashtags": non_party_hashtags,
        "behaviour_comparisons": compute_behaviour_comparisons(data),
        # TODO: behaviour comparison compute seems to slow down computation
        #  noticeably; need to make report statistics computation async.
    }


def generate_user_report_statistics(
    participant: Participant, data: TikTokUserData
) -> ParticipantReportStatistics:
    statistics = compute_user_report_statistics(data)

    return ParticipantReportStatistics.objects.create(
        participant=participant, **statistics
    )
