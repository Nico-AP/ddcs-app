"""Plots for the public (cross-account) report.

Unlike ``user_plots.py`` — which only renders records already computed by
``services.compute_user_report_statistics`` — the functions here also own
their data gathering for now, since there is no persisted "public report
statistics" model (``get_post_data`` is the DB-querying step). It is
cached via Django's cache framework so it is cheap to call from multiple
views; a daily Celery task is expected to take over refreshing it once one
exists.
"""

import logging
from datetime import date, timedelta
from typing import Any

from django.core.cache import cache
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from plotly import graph_objects as go

from ddcs.metadata.models import SyncAttempt, TikTokVideo
from ddcs.reports.config import (
    PARTIES_ORDER,
    PUBLIC_POST_DATA_END_LAG_DAYS,
    PUBLIC_POST_DATA_START_DATE,
)
from ddcs.reports.plots.utils import (
    PARTY_COLOR_OTHER,
    PARTY_COLORS,
    PLOT_CONFIG,
    PLOT_FONT_FAMILY,
    create_plot_html,
    hex_to_rgba,
)
from ddcs.reports.types import (
    DailyAccountPostCountRecord,
    DailyPartyCountRecord,
    PartyCountRecord,
)
from ddcs.reports.utils import load_account_party_mapping

logger = logging.getLogger(__name__)

_POST_DATA_CACHE_KEY = "reports:public_post_data"
# Slightly over a day: a daily Celery task is expected to overwrite this key
# before it expires; the timeout is just a safety net if that task doesn't
# run (see module docstring).
_POST_DATA_CACHE_TIMEOUT = 60 * 60 * 25


def _post_data_date_range() -> tuple[date, date]:
    end = timezone.now().date() - timedelta(days=PUBLIC_POST_DATA_END_LAG_DAYS)
    return PUBLIC_POST_DATA_START_DATE, end


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

    video_counts = {
        (row["user__name"], row["post_date"].isoformat()): row["count"]
        for row in (
            TikTokVideo.objects.filter(
                user__name__in=usernames,
                inferred_create_time__date__gte=start,
                inferred_create_time__date__lte=end,
            )
            .annotate(post_date=TruncDate("inferred_create_time"))
            .values("user__name", "post_date")
            .annotate(count=Count("id_tiktok"))
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
                {"username": username, "party": party, "date": iso, "count": count}
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


def _aggregate_party_counts(
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


def _aggregate_daily_party_counts(
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


def get_party_distribution_all_accounts(
    records: list[DailyAccountPostCountRecord],
) -> dict[str, Any]:
    """Create treemap of total posted-video counts per party, across all
    monitored party accounts."""
    party_counts = sorted(
        _aggregate_party_counts(records), key=lambda c: c["count"], reverse=True
    )
    if not party_counts:
        return {"html": None}

    labels = [c["party"] for c in party_counts]
    values = [c["count"] for c in party_counts]

    fig = go.Figure(
        go.Treemap(
            labels=labels,
            parents=[""] * len(party_counts),
            values=values,
            textinfo="label+value",
            textfont={"size": 28, "family": PLOT_FONT_FAMILY, "color": "black"},
            marker={
                "colors": [
                    hex_to_rgba(PARTY_COLORS.get(party, PARTY_COLOR_OTHER))
                    for party in labels
                ],
                "line": {"width": 0, "color": "white"},
            },
            hovertemplate="<b>%{label}</b><br>Videos: %{value}<extra></extra>",
        )
    )
    fig.update_layout(
        dragmode=False,
        margin={"t": 0, "l": 0, "r": 0, "b": 0},
        font={"size": 25, "color": "black", "family": PLOT_FONT_FAMILY},
        paper_bgcolor="rgba(0,0,0,0)",
        height=450,
    )

    top_party = party_counts[0]
    return {
        "html": create_plot_html(fig),
        "data": {
            "party": top_party["party"],
            "value": top_party["count"],
            "color": PARTY_COLORS.get(top_party["party"], PARTY_COLOR_OTHER),
        },
    }


def get_temporal_party_distribution_all_accounts(
    records: list[DailyAccountPostCountRecord],
) -> dict[str, Any]:
    """Create stacked-area chart of posted-video counts per day, across all
    monitored party accounts."""
    daily_party_counts = _aggregate_daily_party_counts(records)
    if not daily_party_counts:
        return {"html": None}

    party_data: dict[str, dict[str, int]] = {}
    for record in daily_party_counts:
        party_data.setdefault(record["party"], {})[record["date"]] = record["count"]

    min_date = min(r["date"] for r in daily_party_counts)
    max_date = max(r["date"] for r in daily_party_counts)
    start = date.fromisoformat(min_date)
    end = date.fromisoformat(max_date)
    all_dates = [
        (start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)
    ]

    fig = go.Figure()
    for party in reversed(PARTIES_ORDER):
        if party not in party_data:
            continue

        counts = party_data[party]
        fig.add_trace(
            go.Scatter(
                x=all_dates,
                y=[counts.get(d, 0) for d in all_dates],
                name=party,
                mode="lines",
                line={"width": 0},
                stackgroup="one",
                fillcolor=hex_to_rgba(PARTY_COLORS.get(party, PARTY_COLOR_OTHER)),
                hovertemplate="%{y} Videos<extra></extra>",
                hoverlabel={
                    "bgcolor": "white",
                    "font_size": 16,
                    "font_family": PLOT_FONT_FAMILY,
                },
            )
        )

    fig.update_layout(
        xaxis_title="Datum",
        yaxis_title="Anzahl Videos (kumuliert)",
        hovermode="x unified",
        dragmode=False,
        showlegend=True,
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "center",
            "x": 0.5,
            "font": {"size": 18},
        },
        autosize=True,
        height=400,
        minreducedwidth=500,
        font={"size": 25, "color": "black", "family": PLOT_FONT_FAMILY},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        hoverdistance=100,
        hoverlabel={"namelength": 0},
    )

    fig.update_xaxes(
        hoverformat="%d.%m.%Y",
        showgrid=True,
        gridwidth=1,
        gridcolor="gray",
        zeroline=True,
        zerolinewidth=1,
        zerolinecolor="gray",
        tickangle=45,
        tickformat="%d.%m",
        tickfont={"size": 20, "color": "black"},
        title_font={"size": 20},
    )
    fig.update_yaxes(
        showgrid=True,
        gridwidth=1,
        gridcolor="gray",
        zeroline=True,
        zerolinewidth=1,
        zerolinecolor="gray",
        tickfont={"size": 20, "color": "black"},
        title_font={"size": 20},
    )

    return {"html": create_plot_html(fig, config=PLOT_CONFIG)}
