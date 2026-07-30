"""
Factories for generating synthetic ParticipantReportStatistics instances.

Used during development to populate the report view with realistic-looking
data without requiring an actual data donation.
"""

# ruff: noqa: S311, PLR2004

from datetime import UTC, datetime, timedelta
from random import choice, choices, randint, random, uniform

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


# Relative feed volume for synthetic party plots (higher = more videos).
_SYNTHETIC_PARTY_ACTIVITY = {
    "AfD": 12,
    "SPD": 9,
    "CDU/CSU": 8,
    "B90/GRÜNE": 6,
    "Linke": 5,
    "BSW": 4,
    "FDP": 3,
    "Sonstige": 2,
    NO_PARTY_KEY: 1,
}


def _synthetic_party_count_for(party: str) -> int:
    """Draw a non-zero-ish count scaled by party activity weight."""
    weight = _SYNTHETIC_PARTY_ACTIVITY.get(party, 1)
    # Keep small parties sparse; larger parties dominate the series.
    return randint(0, weight)


def _synthetic_party_counts() -> list[PartyCountRecord]:
    return [
        {
            "party": party,
            "count": max(1, _synthetic_party_count_for(party) * randint(2, 4)),
        }
        for party in SYNTHETIC_PARTIES
    ]


def _synthetic_daily_party_counts(days: int = 30) -> list[DailyPartyCountRecord]:
    start = datetime.now(tz=UTC).date() - timedelta(days=days)
    return [
        {
            "date": (start + timedelta(days=i)).isoformat(),
            "party": party,
            "count": _synthetic_party_count_for(party),
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
    "https://www.tiktok.com/@sahra.wagenknecht/video/7664658382707625248",
    "https://www.tiktok.com/@diegruenen/photo/7655671745294257441",
    "https://www.tiktok.com/@alice_weidel_afd/video/7658941918302326048",
    "https://www.tiktok.com/@deinespd/video/7657187761883041057",
    "https://www.tiktok.com/@die.linke/photo/7623456044794055968",
]

_SYNTHETIC_TOP_VIDEO_PARTIES = {
    "sahra.wagenknecht": "BSW",
    "diegruenen": "B90/GRÜNE",
    "alice_weidel_afd": "AfD",
    "deinespd": "SPD",
    "die.linke": "Linke",
}


def _synthetic_top_videos(
    video_ids: list[int], n: int = N_TOP_VIDEOS
) -> list[TopVideoRecord]:
    del video_ids
    videos: list[TopVideoRecord] = []
    for index, url in enumerate(SYNTHETIC_TOP_VIDEO_URLS[:n]):
        video_id = parse_tiktok_video_id_from_url(url)
        username = parse_tiktok_username_from_url(url)
        if video_id is None or not username:
            continue
        videos.append(
            {
                "video_id": video_id,
                "username": username,
                "party": _SYNTHETIC_TOP_VIDEO_PARTIES.get(username, NO_PARTY_KEY),
                # Feed appearances (metadata only — ranking uses total_views).
                "view_count": randint(1, 6),
                "description": SYNTHETIC_DESCRIPTIONS[
                    index % len(SYNTHETIC_DESCRIPTIONS)
                ],
                "watch_share": 0.0,
                "avg_watch_sec": round(2.5 + index * 3.5 + randint(0, 4), 1),
                # Descending overall views so synthetic order matches "viral".
                "total_views": 2_500_000 - index * 400_000 - randint(0, 50_000),
                "liked": index % 2 == 0,
                "shared": index == 0,
                "saved": index in {0, 2},
                "followed_author": index in {0, 1},
                "tiktok_url": url,
            }
        )
    return sorted(
        videos,
        key=lambda video: video["total_views"] or 0,
        reverse=True,
    )


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


_SYNTHETIC_BEHAVIOUR_PERSONAS = (
    "kolibri",
    "faultier",
    "eule",
    "waschbaer",
    "papagei",
    "luchs",
)


def _synthetic_persona_hour(persona: str) -> int:
    if persona == "eule":
        return choice([22, 23, 0, 1, 2, 3, 4, 5])
    if persona == "waschbaer":
        return choice([10, 11, 12, 14, 15, 16, 18, 19, 20, 21])
    return randint(8, 22)


def _synthetic_day_is_active(persona: str, day: datetime) -> bool:
    """Most users are active on ~2/3 of days; Waschbär leans weekend."""
    if persona == "waschbaer":
        return random() < (0.9 if day.weekday() >= 5 else 0.35)
    if persona == "eule":
        return random() < 0.65
    return random() < 0.72


def _synthetic_in_session_gap_seconds(persona: str) -> float:
    """Gap to next watch within a session (<90s so the session stays open)."""
    if persona == "kolibri":
        return uniform(0.2, 0.9) if random() < 0.85 else uniform(1.5, 8.0)
    if persona == "faultier":
        return uniform(12.0, 55.0)
    roll = random()
    if roll < 0.25:
        return uniform(0.2, 0.9)
    return uniform(2.0, 45.0)


def _synthetic_session_length(persona: str) -> int:
    """Videos per session — sized so daily volume looks like real donations."""
    if persona == "kolibri":
        return randint(50, 110)
    if persona == "faultier":
        return randint(35, 80)
    if persona == "eule":
        return randint(40, 95)
    return randint(40, 100)


def _synthetic_watch_history(persona: str) -> list[dict]:
    """Build a dense, persona-biased watch timeline (~real donation volume)."""
    start = REPORT_FIRST_DATE_TO_INCLUDE
    n_calendar_days = 30

    for _ in range(5):
        watches: list[dict] = []
        video_id = 0
        for day_offset in range(n_calendar_days):
            day = start + timedelta(days=day_offset)
            if not _synthetic_day_is_active(persona, day):
                continue
            n_sessions = randint(2, 5)
            for _session in range(n_sessions):
                cursor = day + timedelta(
                    hours=_synthetic_persona_hour(persona),
                    minutes=randint(0, 45),
                    seconds=randint(0, 50),
                )
                for _video in range(_synthetic_session_length(persona)):
                    watches.append(
                        {
                            "date": cursor,
                            "link": (f"https://www.tiktok.com/@user/video/{video_id}"),
                            "video_id": video_id,
                        }
                    )
                    video_id += 1
                    cursor = cursor + timedelta(
                        seconds=_synthetic_in_session_gap_seconds(persona)
                    )
        if len(watches) >= 200:
            return watches
    return watches


def _synthetic_behaviour_comparisons(
    political_video_ids: frozenset[int] | None = None,
) -> list[dict]:
    # Pick a spirit-animal persona so full synthetic-report refreshes can
    # land on different typologies while filters still reuse session cache.
    persona = choice(_SYNTHETIC_BEHAVIOUR_PERSONAS)
    pol_ids = list(political_video_ids or [])
    non_pol_ids = [randint(1000000, 9999999) for _ in range(20)]
    watch_history = _synthetic_watch_history(persona)

    # Luchs: high share of engagements on political content.
    if persona == "luchs" and pol_ids:
        n_pol_likes = min(len(pol_ids), randint(12, 18))
        n_pol_shares = min(len(pol_ids), randint(6, 10))
    else:
        n_pol_likes = min(10, len(pol_ids)) if pol_ids else 0
        n_pol_shares = min(4, len(pol_ids)) if pol_ids else 0
    political_likes = (
        [
            _synthetic_engagement_record(video_id, day_offset=i % 20)
            for i, video_id in enumerate(choices(pol_ids, k=n_pol_likes))
        ]
        if n_pol_likes
        else []
    )
    # Papagei: like almost everything; others: sparse non-political likes.
    if persona == "papagei":
        like_ids = [w["video_id"] for w in watch_history if random() < 0.85]
    elif persona == "luchs":
        like_ids = list(non_pol_ids[: randint(1, 3)])
    else:
        like_ids = list(non_pol_ids[: randint(3, 10)])
    other_likes = [
        _synthetic_engagement_record(video_id, day_offset=i % 20)
        for i, video_id in enumerate(like_ids)
    ]
    political_shares = (
        [
            _synthetic_engagement_record(video_id, day_offset=i % 15)
            for i, video_id in enumerate(choices(pol_ids, k=n_pol_shares))
        ]
        if n_pol_shares
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
