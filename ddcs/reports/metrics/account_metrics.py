from datetime import date, timedelta

from django.core.cache import cache
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone

from ddcs.metadata.models import SyncAttempt, TikTokVideo
from ddcs.reports.config import (
    PARTIES_ORDER,
    PUBLIC_POST_DATA_END_LAG_DAYS,
    PUBLIC_POST_DATA_START_DATE,
)
from ddcs.reports.types import (
    DailyAccountPostCountRecord,
    DailyPartyCountRecord,
    PartyCountRecord,
)
from ddcs.reports.utils import load_account_party_mapping

_POST_DATA_CACHE_KEY = "reports:public_post_data"

# Slightly over a day: a daily Celery task is expected to overwrite this key
# before it expires; the timeout is just a safety net if that task doesn't
# run (see module docstring).
_POST_DATA_CACHE_TIMEOUT = 60 * 60 * 25


def _post_data_date_range() -> tuple[date, date]:
    end = timezone.now().date() - timedelta(days=PUBLIC_POST_DATA_END_LAG_DAYS)
    return PUBLIC_POST_DATA_START_DATE, end


def _recode_party(party: str) -> str:
    """Merge inconsistent CDU/CSU and Grüne/B90 spellings into one bucket
    each. Anything else passes through unchanged, original casing intact.
    """
    party_recodes = {
        "cdu": "CDU/CSU",
        "csu": "CDU/CSU",
        "grüne": "B90/GRÜNE",
        "b90": "B90/GRÜNE",
        "link": "Linke",
    }
    stripped = party.strip()
    recoded_party = party_recodes.get(stripped.lower(), stripped)

    if recoded_party not in PARTIES_ORDER:
        recoded_party = "Sonstige"

    return recoded_party


def _compute_post_data() -> list[DailyAccountPostCountRecord]:
    """Build the (account, date) base dataset for the public report.

    For each monitored account and each date in the report window, records
    how many TikTokVideos that account posted on that date. ``count`` is
    ``None`` instead of 0 when no videos were found *and* there is no
    successful ``SyncAttempt`` for that account/date — i.e. the account's
    coverage for that day is unknown rather than a confirmed zero.
    """
    account_party_map = load_account_party_mapping()
    usernames = list(account_party_map.keys())
    start, end = _post_data_date_range()

    # `APIVideoInfos.create_time` is the authoritative API-reported
    # publication timestamp.
    video_counts = {
        (row["user__name"], row["post_date"].isoformat()): row["count"]
        for row in (
            TikTokVideo.objects.filter(
                user__name__in=usernames,
                api_infos__create_time__date__gte=start,
                api_infos__create_time__date__lte=end,
            )
            .annotate(post_date=TruncDate("api_infos__create_time"))
            .values("user__name", "post_date")
            .annotate(count=Count("id_tiktok", distinct=True))
        )
    }

    synced_days = {
        (username, target_date.isoformat())
        for username, target_date in SyncAttempt.objects.filter(
            user__name__in=usernames,
            target_date__gte=start,
            target_date__lte=end,
            status=SyncAttempt.Status.SUCCESS,
        ).values_list("user__name", "target_date")
    }

    all_dates = [start + timedelta(days=i) for i in range((end - start).days + 1)]

    records: list[DailyAccountPostCountRecord] = []
    for username in usernames:
        party = account_party_map[username]
        for day in all_dates:
            iso = day.isoformat()
            count = video_counts.get((username, iso), 0)
            if count == 0 and (username, iso) not in synced_days:
                count = None
            records.append(
                {
                    "username": username,
                    "party": _recode_party(party),
                    "date": iso,
                    "count": count,
                }
            )
    return records


def get_post_data(*, force_refresh: bool = False) -> list[DailyAccountPostCountRecord]:
    """Return the cached (account, date) post-count base dataset.

    Computed lazily on first call and cached for ``_POST_DATA_CACHE_TIMEOUT``
    seconds. Pass ``force_refresh=True`` to recompute and re-cache
    immediately (for the future daily Celery refresh task).
    """
    if force_refresh:
        cache.delete(_POST_DATA_CACHE_KEY)
    return cache.get_or_set(
        _POST_DATA_CACHE_KEY, _compute_post_data, _POST_DATA_CACHE_TIMEOUT
    )


def refresh_post_data() -> list[DailyAccountPostCountRecord]:
    """Thin wrapper around get_post_data()."""
    return get_post_data(force_refresh=True)


def aggregate_party_counts(
    records: list[DailyAccountPostCountRecord],
) -> list[PartyCountRecord]:
    """Sum post counts per party across all accounts and dates.

    Entries with ``count=None`` (unknown coverage) don't contribute.
    """
    counts: dict[str, int] = {}
    for record in records:
        if record["count"] is None:
            continue
        counts[record["party"]] = counts.get(record["party"], 0) + record["count"]

    return [{"party": party, "count": count} for party, count in counts.items()]


def aggregate_daily_party_counts(
    records: list[DailyAccountPostCountRecord],
) -> list[DailyPartyCountRecord]:
    """Sum post counts per day per party, across all accounts.

    Entries with ``count=None`` (unknown coverage) don't contribute.
    """
    counts: dict[tuple[str, str], int] = {}
    for record in records:
        if record["count"] is None:
            continue
        key = (record["date"], record["party"])
        counts[key] = counts.get(key, 0) + record["count"]

    return [
        {"date": day, "party": party, "count": count}
        for (day, party), count in sorted(counts.items(), key=lambda x: x[0])
    ]
