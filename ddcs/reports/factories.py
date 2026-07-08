"""
Factories for generating synthetic ParticipantReportStatistics instances.

Used during development to populate the report view with realistic-looking
data without requiring an actual data donation.
"""

# ruff: noqa: S311

from datetime import UTC, datetime, timedelta
from random import choices, randint

from ddm.participation.models import Participant

from ddcs.core.types import TikTokUserData
from ddcs.reports.behaviour_metrics import compute_behaviour_comparisons
from ddcs.reports.config import (
    N_TOP_VIDEOS,
    NO_PARTY_KEY,
    PARTIES_ORDER,
    REPORT_FIRST_DATE_TO_INCLUDE,
)
from ddcs.reports.models import ParticipantReportStatistics
from ddcs.reports.types import (
    DailyAccountPostCountRecord,
    DailyPartyCountRecord,
    PartyCountRecord,
    TopVideoRecord,
)
from ddcs.reports.utils import (
    parse_tiktok_username_from_url,
    parse_tiktok_video_id_from_url,
)

# Mirrors what the real pipeline emits: every entry in PARTIES_ORDER,
# including NO_PARTY_KEY for non-party political (and neutral) videos.
SYNTHETIC_PARTIES = list(PARTIES_ORDER)

SYNTHETIC_USERNAMES = [
    "spd_official",
    "cdu_deutschland",
    "gruene_official",
    "fdp_official",
    "afd_official",
    "dielinke",
    "bsw_official",
]

SYNTHETIC_DESCRIPTIONS = [
    "Wichtige Politik Nachrichten aus dem Bundestag",
    "Bundestagswahl 2025 - Demokratie stärken",
    "Wahlkampf Update von der Regierung",
    "Junge Wählerinnen und Wähler auf TikTok",
    "Koalitionsverhandlungen und aktuelle Debatten",
    "News zur Bundestagswahl und Demokratie",
    "Diskussion über Wirtschaft und Klimaschutz",
    "Statement zur aktuellen Regierungspolitik",
]


def _synthetic_party_counts() -> list[PartyCountRecord]:
    return [{"party": party, "count": randint(1, 50)} for party in SYNTHETIC_PARTIES]


def _synthetic_daily_party_counts(days: int = 30) -> list[DailyPartyCountRecord]:
    start = datetime.now(tz=UTC).date() - timedelta(days=days)
    return [
        {
            "date": (start + timedelta(days=i)).isoformat(),
            "party": party,
            "count": randint(0, 10),
        }
        for i in range(days)
        for party in SYNTHETIC_PARTIES
    ]


# One synthetic account per party, for the public (cross-account) plots.
SYNTHETIC_POST_PARTIES = [party for party in PARTIES_ORDER if party != NO_PARTY_KEY]
SYNTHETIC_POST_USERNAMES = {
    party: f"{party.lower().replace('/', '_')}_official"
    for party in SYNTHETIC_POST_PARTIES
}


def get_synthetic_post_data(days: int = 30) -> list[DailyAccountPostCountRecord]:
    """Generate synthetic (account, date) post-count records, for dev
    inspection of the public plots (``plots/public_plots.py``) without a
    real database of monitored accounts.

    Mirrors what ``get_post_data`` emits: one entry per (account, date),
    with occasional ``None`` counts standing in for unsynced days.
    """
    start = datetime.now(tz=UTC).date() - timedelta(days=days)
    return [
        {
            "username": SYNTHETIC_POST_USERNAMES[party],
            "party": party,
            "date": (start + timedelta(days=i)).isoformat(),
            "count": choices([None, 0, randint(1, 6)], weights=[1, 3, 6], k=1)[0],
        }
        for party in SYNTHETIC_POST_PARTIES
        for i in range(days)
    ]


def _synthetic_descriptions_by_video(video_ids: list[int]) -> dict[int, str]:
    return {video_id: choices(SYNTHETIC_DESCRIPTIONS)[0] for video_id in video_ids}


SYNTHETIC_TOP_VIDEO_URLS: list[str] = [
    "https://www.tiktok.com/@alice_weidel_afd/video/7658941918302326048",
    "https://www.tiktok.com/@deinespd/video/7657187761883041057",
    "https://www.tiktok.com/@die.linke/photo/7623456044794055968",
]

_SYNTHETIC_TOP_VIDEO_PARTIES = {
    "alice_weidel_afd": "AfD",
    "deinespd": "SPD",
    "die.linke": "Linke",
}


def _synthetic_top_videos(
    video_ids: list[int], n: int = N_TOP_VIDEOS
) -> list[TopVideoRecord]:
    del video_ids, n
    videos: list[TopVideoRecord] = []
    for index, url in enumerate(SYNTHETIC_TOP_VIDEO_URLS):
        video_id = parse_tiktok_video_id_from_url(url)
        username = parse_tiktok_username_from_url(url)
        if video_id is None or not username:
            continue
        videos.append(
            {
                "video_id": video_id,
                "username": username,
                "party": _SYNTHETIC_TOP_VIDEO_PARTIES.get(username, NO_PARTY_KEY),
                "view_count": len(SYNTHETIC_TOP_VIDEO_URLS) - index,
                "description": SYNTHETIC_DESCRIPTIONS[
                    index % len(SYNTHETIC_DESCRIPTIONS)
                ],
                "tiktok_url": url,
            }
        )
    return videos


def _synthetic_description_list() -> list[str]:
    return choices(SYNTHETIC_DESCRIPTIONS, k=randint(20, 60))


def _synthetic_engagement_record(
    video_id: int,
    *,
    day_offset: int = 0,
) -> dict:
    return {
        "date": REPORT_FIRST_DATE_TO_INCLUDE + timedelta(days=day_offset),
        "link": f"https://www.tiktok.com/@user/video/{video_id}",
        "video_id": video_id,
    }


def _synthetic_behaviour_comparisons(
    political_video_ids: frozenset[int] | None = None,
) -> list[dict]:
    start = REPORT_FIRST_DATE_TO_INCLUDE
    pol_ids = list(political_video_ids or [])
    non_pol_ids = [randint(1000000, 9999999) for _ in range(12)]

    watch_history = [
        {
            "date": start + timedelta(days=i % 30, hours=(i * 3) % 24),
            "link": f"https://www.tiktok.com/@user/video/{i}",
            "video_id": i,
        }
        for i in range(120)
    ]

    political_likes = (
        [
            _synthetic_engagement_record(video_id, day_offset=i % 20)
            for i, video_id in enumerate(choices(pol_ids, k=min(10, len(pol_ids))))
        ]
        if pol_ids
        else []
    )
    other_likes = [
        _synthetic_engagement_record(video_id, day_offset=i % 20)
        for i, video_id in enumerate(non_pol_ids[:15])
    ]
    political_shares = (
        [
            _synthetic_engagement_record(video_id, day_offset=i % 15)
            for i, video_id in enumerate(choices(pol_ids, k=min(4, len(pol_ids))))
        ]
        if pol_ids
        else []
    )

    return compute_behaviour_comparisons(
        TikTokUserData(
            watch_history=watch_history,
            liked_videos=political_likes + other_likes,
            shared_videos=political_shares,
        ),
        political_video_ids or frozenset(),
    )


def get_synthetic_report_statistics(
    participant: Participant,
) -> ParticipantReportStatistics:
    """Generate a synthetic ParticipantReportStatistics instance for
    testing and report inspection.

    Creates realistic-looking but randomly generated data. The instance is saved
    to the database and associated with the given participant.
    """
    seen_pol_video_ids = [randint(1000000, 9999999) for _ in range(randint(20, 100))]
    liked_pol_video_ids = choices(seen_pol_video_ids, k=randint(5, 20))
    followed_pol_users = choices(
        SYNTHETIC_USERNAMES, k=randint(1, len(SYNTHETIC_USERNAMES))
    )

    return ParticipantReportStatistics(
        participant=participant,
        # Pad the total above the political count so the share-political ratio
        # in the report stays plausibly under 100%.
        videos_seen_count_total=randint(
            len(seen_pol_video_ids) * 2, len(seen_pol_video_ids) * 5
        ),
        seen_pol_video_ids=seen_pol_video_ids,
        liked_pol_video_ids=liked_pol_video_ids,
        followed_pol_users=followed_pol_users,
        party_counts=_synthetic_party_counts(),
        daily_party_counts=_synthetic_daily_party_counts(),
        hashtags_by_pol_video=_synthetic_descriptions_by_video(seen_pol_video_ids),
        top_videos=_synthetic_top_videos(seen_pol_video_ids),
        party_hashtags=_synthetic_description_list(),
        non_party_hashtags=_synthetic_description_list(),
        behaviour_comparisons=_synthetic_behaviour_comparisons(
            frozenset(seen_pol_video_ids)
        ),
    )
