"""
Factories for generating synthetic ParticipantReportStatistics instances.

Used during development to populate the report view with realistic-looking
data without requiring an actual data donation.
"""

# ruff: noqa: S311

from datetime import UTC, datetime, timedelta
from random import choices, randint, shuffle

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

SYNTHETIC_HASHTAGS = [
    "politik",
    "bundestagswahl",
    "demokratie",
    "deutschland",
    "wahl2025",
    "bundestag",
    "wahlkampf",
    "news",
    "regierung",
    "jungealternative",
    "jungeliberale",
    "jungeunion",
    "jusos",
    "katringoertingeckardt",
    "keinechancedercdu",
    "koalition",
    "kubicki",
    "larsklingbeil",
    "lauterbach",
    "linke",
    "linkesindzecke",
    "linkewohnkngssitutuation",
    "linksfraktion",
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


def _synthetic_hashtags_by_video(video_ids: list[int]) -> dict[int, list[str]]:
    return {
        video_id: choices(SYNTHETIC_HASHTAGS, k=randint(0, 5)) for video_id in video_ids
    }


def _synthetic_top_videos(
    video_ids: list[int], n: int = N_TOP_VIDEOS
) -> list[TopVideoRecord]:
    shuffled = list(set(video_ids))
    shuffle(shuffled)
    return [
        {
            "video_id": video_id,
            "username": choices(SYNTHETIC_USERNAMES)[0],
            "party": choices(SYNTHETIC_PARTIES)[0],
            "view_count": randint(1, 20),
            "hashtags": choices(SYNTHETIC_HASHTAGS, k=randint(0, 5)),
        }
        for video_id in shuffled[:n]
    ]


def _synthetic_hashtag_list() -> list[str]:
    return choices(SYNTHETIC_HASHTAGS, k=randint(150, 500))


def _synthetic_behaviour_comparisons() -> list[dict]:
    start = REPORT_FIRST_DATE_TO_INCLUDE
    watch_history = [
        {
            "date": start + timedelta(days=i % 30, hours=(i * 3) % 24),
            "link": f"https://www.tiktok.com/@user/video/{i}",
            "video_id": i,
        }
        for i in range(120)
    ]
    return compute_behaviour_comparisons(TikTokUserData(watch_history=watch_history))


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
        hashtags_by_pol_video=_synthetic_hashtags_by_video(seen_pol_video_ids),
        top_videos=_synthetic_top_videos(seen_pol_video_ids),
        party_hashtags=_synthetic_hashtag_list(),
        non_party_hashtags=_synthetic_hashtag_list(),
        behaviour_comparisons=_synthetic_behaviour_comparisons(),
    )
