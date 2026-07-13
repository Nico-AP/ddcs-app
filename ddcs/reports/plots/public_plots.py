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

from plotly import graph_objects as go

from ddcs.reports.config import (
    PARTIES_ORDER,
)
from ddcs.reports.metrics.account_metrics import (
    aggregate_daily_party_counts,
    aggregate_party_counts,
)
from ddcs.reports.plots.utils import (
    PARTY_COLOR_OTHER,
    PARTY_COLORS,
    PLOT_CONFIG,
    PLOT_CORNER_RADIUS,
    PLOT_FONT_FAMILY,
    TEMPORAL_PARTY_PLOT_LEGEND,
    create_plot_html,
    hex_to_rgba,
)
from ddcs.reports.types import (
    DailyAccountPostCountRecord,
)

logger = logging.getLogger(__name__)


def get_party_distribution_all_accounts(
    records: list[DailyAccountPostCountRecord],
) -> dict[str, Any]:
    """Create treemap of total posted-video counts per party, across all
    monitored party accounts."""
    party_counts = sorted(
        aggregate_party_counts(records), key=lambda c: c["count"], reverse=True
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
                # Plotly defaults marker.pad.t to 56 (room for a branch's own
                # label above its children) vs. 14 on the other sides — this
                # treemap is flat with an unlabeled root, so that default
                # left a large blank strip above the tiles. Match all sides.
                "pad": {"t": 14, "l": 14, "r": 14, "b": 14},
                "cornerradius": PLOT_CORNER_RADIUS,
            },
            hovertemplate="<b>%{label}</b><br>Videos: %{value}<extra></extra>",
            # All parties are root-level tiles (single level, no drill-down),
            # so the breadcrumb bar would only ever show empty; disable it
            # too (harmless either way once marker.pad.t is fixed above).
            pathbar={"visible": False},
        )
    )
    fig.update_layout(
        dragmode=False,
        margin={"t": 0, "l": 0, "r": 0, "b": 0},
        font={"size": 25, "color": "black", "family": PLOT_FONT_FAMILY},
        paper_bgcolor="rgba(0,0,0,0)",
        height=400,
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
    """Create stacked bar chart of posted-video counts per day, across all
    monitored party accounts."""
    daily_party_counts = aggregate_daily_party_counts(records)
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
            go.Bar(
                x=all_dates,
                y=[counts.get(d, 0) for d in all_dates],
                name=party,
                marker={
                    "color": hex_to_rgba(PARTY_COLORS.get(party, PARTY_COLOR_OTHER))
                },
                hovertemplate="%{y} Videos<extra></extra>",
                hoverlabel={
                    "bgcolor": "white",
                    "font_size": 16,
                    "font_family": PLOT_FONT_FAMILY,
                },
            )
        )

    fig.update_layout(
        barmode="stack",
        xaxis_title="Datum",
        yaxis_title="",
        hovermode="x unified",
        dragmode=False,
        showlegend=True,
        legend=TEMPORAL_PARTY_PLOT_LEGEND,
        autosize=True,
        height=400,
        minreducedwidth=500,
        font={"size": 25, "color": "black", "family": PLOT_FONT_FAMILY},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        hoverdistance=100,
        hoverlabel={"namelength": 0},
        bargap=0.15,
        barcornerradius=PLOT_CORNER_RADIUS,
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
        automargin=True,
        showgrid=True,
        gridwidth=1,
        gridcolor="gray",
        zeroline=True,
        zerolinewidth=1,
        zerolinecolor="gray",
        tickfont={"size": 20, "color": "black"},
        title_font={"size": 1},
        title_standoff=0,
    )

    return {"html": create_plot_html(fig, config=PLOT_CONFIG)}
