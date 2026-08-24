import re
from collections import Counter
from collections.abc import Iterable
from datetime import datetime

from django.db.models import Prefetch

from ddcs.core.types import (
    FollowedAccountRecord,
    LikedVideoRecord,
    TikTokUserData,
    WatchHistoryRecord,
)
from ddcs.metadata.models import TikTokVideo
from ddcs.metadata.research_api.models import APIVideoInfos, APIVideoStatistics
from ddcs.reports.behaviour_metrics import (
    avg_inferred_watch_sec_by_video,
    compute_behaviour_comparisons,
)
from ddcs.reports.config import (
    N_TOP_VIDEOS,
    NO_PARTY_KEY,
    PARTIES_ORDER,
    REPORT_FIRST_DATE_TO_INCLUDE,
)
from ddcs.reports.metrics.account_metrics import _recode_party
from ddcs.reports.types import (
    DailyPartyCountRecord,
    PartyCountRecord,
    ReportStatistics,
    TopVideoRecord,
)
from ddcs.reports.utils import load_account_party_mapping

_LINK_USERNAME_RE = re.compile(r"tiktok\.com/@([^/]+)/", re.IGNORECASE)


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


def _extract_username_from_link(link: str) -> str | None:
    if not link:
        return None
    match = _LINK_USERNAME_RE.search(link)
    return match.group(1) if match else None


def _party_videos_from_watch_history(
    watch_history: list[WatchHistoryRecord],
    account_party_mapping: dict[str, str],
) -> tuple[dict[int, str], dict[int, str]]:
    """Map watched video IDs to party/username when the link is a party account."""
    party_map: dict[int, str] = {}
    username_map: dict[int, str] = {}
    for record in watch_history or []:
        date = record.get("date")
        video_id = record.get("video_id")
        if not isinstance(date, datetime) or date < REPORT_FIRST_DATE_TO_INCLUDE:
            continue
        if video_id is None:
            continue
        username = _extract_username_from_link(record.get("link") or "")
        if username and username in account_party_mapping:
            party_map[video_id] = _recode_party(account_party_mapping[username])
            username_map[video_id] = username
    return party_map, username_map


def _merge_political_video_metadata(
    party_map: dict[int, str],
    username_map: dict[int, str],
    extra_party_map: dict[int, str],
    extra_username_map: dict[int, str],
) -> None:
    for video_id, party in extra_party_map.items():
        party_map[video_id] = party
        username_map[video_id] = extra_username_map[video_id]


def _build_political_video_metadata(
    party_account_videos: Iterable,
    non_party_political_videos: Iterable,
    user_party_map: dict[str, str],
) -> tuple[dict[int, str], dict[int, str]]:
    """Return ``(video_id -> party, video_id -> username)`` for both kinds of
    political videos.

    Party-account videos map to the party from ``user_party_map`` after
    ``_recode_party`` (CDU/CSU merge; minor parties → Sonstige).
    Non-party political videos (matched via a monitored hashtag) map to
    ``NO_PARTY_KEY``; their descriptions feed the non-party wordcloud.
    """
    party_map: dict[int, str] = {}
    username_map: dict[int, str] = {}

    for video in party_account_videos:
        username = video.user.name
        if username in user_party_map:
            party_map[video.id_tiktok] = _recode_party(user_party_map[username])
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
        if date < REPORT_FIRST_DATE_TO_INCLUDE:
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


def _first_non_empty_description(video: TikTokVideo) -> str:
    for info in video.api_infos.all():
        if info.description and info.description.strip():
            return info.description.strip()
    return ""


def _latest_total_views(video: TikTokVideo) -> int | None:
    for stats in video.statistics.all():
        if stats.view_count is not None:
            return int(stats.view_count)
    return None


def _get_descriptions_by_video(video_ids: list[int]) -> dict[int, str]:
    """Return a map of video id_tiktok -> description text for the given IDs."""
    if not video_ids:
        return {}

    videos = TikTokVideo.objects.filter(id_tiktok__in=video_ids).prefetch_related(
        Prefetch(
            "api_infos",
            queryset=APIVideoInfos.objects.order_by("-updated_at"),
        ),
    )

    return {video.id_tiktok: _first_non_empty_description(video) for video in videos}


def _get_total_views_by_video(video_ids: list[int]) -> dict[int, int]:
    """Return TikTok Research API view counts keyed by ``id_tiktok``."""
    if not video_ids:
        return {}

    videos = TikTokVideo.objects.filter(id_tiktok__in=video_ids).prefetch_related(
        Prefetch(
            "statistics",
            queryset=APIVideoStatistics.objects.order_by("-updated_at"),
        ),
    )
    result: dict[int, int] = {}
    for video in videos:
        total_views = _latest_total_views(video)
        if total_views is not None:
            result[video.id_tiktok] = total_views
    return result


def _get_top_videos(  # noqa: PLR0913
    seen_pol_video_ids: list[int],
    video_party_map: dict[int, str],
    username_by_video: dict[int, str],
    descriptions_by_video: dict[int, str],
    *,
    liked_video_ids: set[int] | None = None,
    shared_video_ids: set[int] | None = None,
    saved_video_ids: set[int] | None = None,
    followed_usernames: set[str] | None = None,
    avg_watch_sec_by_video: dict[int, float] | None = None,
    total_views_by_video: dict[int, int] | None = None,
    n: int = N_TOP_VIDEOS,
) -> list[TopVideoRecord]:
    """Build top N political videos by overall TikTok views (API).

    Candidates are political videos that appear in the participant's watch
    history. Ranking uses Research API ``view_count``; feed appearance count
    and engagement flags are attached as metadata only.
    """
    liked = liked_video_ids or set()
    shared = shared_video_ids or set()
    saved = saved_video_ids or set()
    followed = followed_usernames or set()
    avg_watch = avg_watch_sec_by_video or {}
    total_views = total_views_by_video or {}
    feed_counts = Counter(seen_pol_video_ids)
    total_watches = len(seen_pol_video_ids)
    ranked_ids = sorted(
        feed_counts.keys(),
        key=lambda video_id: (
            total_views.get(video_id) is not None,
            total_views.get(video_id) or 0,
            feed_counts[video_id],
        ),
        reverse=True,
    )[:n]
    return [
        {
            "video_id": video_id,
            "username": username_by_video.get(video_id, ""),
            "view_count": feed_counts[video_id],
            "party": video_party_map.get(video_id),
            "description": descriptions_by_video.get(video_id, ""),
            "watch_share": (
                feed_counts[video_id] / total_watches if total_watches else 0.0
            ),
            "avg_watch_sec": avg_watch.get(video_id),
            "total_views": total_views.get(video_id),
            "liked": video_id in liked,
            "shared": video_id in shared,
            "saved": video_id in saved,
            "followed_author": username_by_video.get(video_id, "") in followed,
        }
        for video_id in ranked_ids
    ]


def compute_user_report_metrics(data: TikTokUserData) -> ReportStatistics:
    # User activities
    seen_video_ids = _get_video_id_list(data.watch_history)
    liked_video_ids = _get_video_id_list(data.liked_videos)
    shared_video_ids = _get_video_id_list(data.shared_videos)
    saved_video_ids = _get_video_id_list(data.video_bookmarks)
    followed_user_names = _get_username_list(data.followed_accounts)

    # Political content
    account_party_mapping = load_account_party_mapping()
    political_usernames = list(account_party_mapping.keys())
    seen_video_id_set = set(seen_video_ids)

    link_party_map, link_username_map = _party_videos_from_watch_history(
        data.watch_history or [], account_party_mapping
    )

    party_account_videos = TikTokVideo.objects.filter(
        id_tiktok__in=seen_video_id_set,
        user__name__in=political_usernames,
    ).select_related("user")
    non_party_political_videos = (
        TikTokVideo.objects.filter(
            id_tiktok__in=seen_video_id_set,
            hashtags__monitor_api=True,
        )
        .exclude(user__name__in=political_usernames)
        .select_related("user")
        .distinct()
    )

    video_party_map, video_username_map = _build_political_video_metadata(
        party_account_videos, non_party_political_videos, account_party_mapping
    )
    _merge_political_video_metadata(
        video_party_map, video_username_map, link_party_map, link_username_map
    )
    political_video_id_set = set(video_party_map.keys())
    political_username_set = set(political_usernames)

    # Generate data used by report
    seen_pol_video_ids = [v for v in seen_video_ids if v in political_video_id_set]
    liked_pol_video_ids = list(set(liked_video_ids) & political_video_id_set)
    followed_pol_users = list(set(followed_user_names) & political_username_set)

    party_counts = _compute_party_counts(seen_video_ids, video_party_map)
    daily_party_counts = _compute_daily_party_counts(
        data.watch_history or [], video_party_map
    )
    descriptions_by_pol_video = _get_descriptions_by_video(seen_pol_video_ids)
    top_videos = _get_top_videos(
        seen_pol_video_ids,
        video_party_map,
        video_username_map,
        descriptions_by_pol_video,
        liked_video_ids=set(liked_video_ids),
        shared_video_ids=set(shared_video_ids),
        saved_video_ids=set(saved_video_ids),
        followed_usernames=set(followed_user_names),
        avg_watch_sec_by_video=avg_inferred_watch_sec_by_video(
            data.watch_history or []
        ),
        total_views_by_video=_get_total_views_by_video(seen_pol_video_ids),
    )

    party_hashtags: list[str] = []
    non_party_hashtags: list[str] = []
    for video_id, description in descriptions_by_pol_video.items():
        if not description:
            continue
        if video_party_map.get(video_id) == NO_PARTY_KEY:
            non_party_hashtags.append(description)
        else:
            party_hashtags.append(description)

    return {
        "videos_seen_count_total": len(seen_video_ids),
        "seen_pol_video_ids": seen_pol_video_ids,
        "liked_pol_video_ids": liked_pol_video_ids,
        "followed_pol_users": followed_pol_users,
        "party_counts": party_counts,
        "daily_party_counts": daily_party_counts,
        "hashtags_by_pol_video": descriptions_by_pol_video,
        "top_videos": top_videos,
        "party_hashtags": party_hashtags,
        "non_party_hashtags": non_party_hashtags,
        "behaviour_comparisons": compute_behaviour_comparisons(
            data, frozenset(political_video_id_set)
        ),
        # TODO: behaviour comparison compute seems to slow down computation
        #  noticeably; need to make report statistics computation async.
    }
