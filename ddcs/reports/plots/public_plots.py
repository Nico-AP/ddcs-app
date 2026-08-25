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
    TEMPORAL_AREA_LINE,
    TEMPORAL_HOVER_BG,
    TEMPORAL_HOVER_BORDER,
    TEMPORAL_HOVER_FONT_SIZE,
    TEMPORAL_HOVER_FONT_SIZE_COMPACT,
    TEMPORAL_PARTY_PLOT_LEGEND,
    TEMPORAL_PLOT_HEIGHT,
    create_plot_html,
    hex_to_rgba,
    temporal_plot_xaxis_tickvals,
)
from ddcs.reports.types import (
    DailyAccountPostCountRecord,
)

logger = logging.getLogger(__name__)

_DEFAULT_BAR_HEIGHT_PER_PARTY = 50
_DEFAULT_BAR_MIN_HEIGHT = 200


def _bar_chart_height(n: int) -> int:
    """Fixed height for non-dashboard (non-compact) bar charts."""
    return max(n * _DEFAULT_BAR_HEIGHT_PER_PARTY, _DEFAULT_BAR_MIN_HEIGHT)


def _bar_chart_font_size(*, compact: bool) -> int:
    return 12 if compact else 14


def _bar_chart_margin(*, compact: bool) -> dict[str, int]:
    if compact:
        return {"t": 4, "l": 4, "r": 56, "b": 4}
    return {"t": 10, "l": 10, "r": 60, "b": 10}


_NEAR_MAX_LABEL_THRESHOLD = 0.92


def _bar_text_kwargs(
    *,
    compact: bool,
    font_size: int,
    values: list[float] | list[int],
) -> dict[str, Any]:
    """Black outside labels; inside (white) only for bars near the axis max."""
    if not compact:
        return {
            "textposition": "outside",
            "textfont": {"size": font_size, "family": PLOT_FONT_FAMILY},
        }

    max_val = max(values) if values else 0
    threshold = max_val * _NEAR_MAX_LABEL_THRESHOLD
    positions = ["inside" if max_val and v >= threshold else "outside" for v in values]
    return {
        "textposition": positions,
        "insidetextanchor": "end",
        "constraintext": "none",
        "outsidetextfont": {
            "size": font_size,
            "family": PLOT_FONT_FAMILY,
            "color": "black",
        },
        "insidetextfont": {
            "size": font_size,
            "family": PLOT_FONT_FAMILY,
            "color": "white",
        },
    }


def _bar_chart_size_kwargs(*, compact: bool, n: int) -> dict[str, Any]:
    """Compact charts fill their CSS container; others use a fixed height."""
    if compact:
        return {"autosize": True}
    return {"height": _bar_chart_height(n)}


def build_party_distribution_figure(
    records: list[DailyAccountPostCountRecord],
    *,
    compact: bool = False,
) -> go.Figure | None:
    """Return the party-video treemap figure, or None when there is no data."""
    party_counts = sorted(
        aggregate_party_counts(records), key=lambda c: c["count"], reverse=True
    )
    if not party_counts:
        return None

    labels = [c["party"] for c in party_counts]
    values = [c["count"] for c in party_counts]

    fig = go.Figure(
        go.Treemap(
            labels=labels,
            parents=[""] * len(party_counts),
            values=values,
            textinfo="label+value",
            textfont={
                "size": 22 if compact else 28,
                "family": PLOT_FONT_FAMILY,
                "color": "black",
            },
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
    layout: dict[str, Any] = {
        "dragmode": False,
        "margin": {"t": 0, "l": 0, "r": 0, "b": 0},
        "font": {
            "size": 20 if compact else 25,
            "color": "black",
            "family": PLOT_FONT_FAMILY,
        },
        "paper_bgcolor": "rgba(0,0,0,0)",
    }
    if compact:
        layout["autosize"] = True
    else:
        layout["height"] = 400
    fig.update_layout(**layout)
    return fig


def get_party_distribution_all_accounts(
    records: list[DailyAccountPostCountRecord],
    *,
    compact: bool = False,
) -> dict[str, Any]:
    """Create treemap of total posted-video counts per party, across all
    monitored party accounts."""
    party_counts = sorted(
        aggregate_party_counts(records), key=lambda c: c["count"], reverse=True
    )
    fig = build_party_distribution_figure(records, compact=compact)
    if fig is None or not party_counts:
        return {"html": None}

    top_party = party_counts[0]
    return {
        "html": create_plot_html(fig, config=PLOT_CONFIG),
        "data": {
            "party": top_party["party"],
            "value": top_party["count"],
            "color": PARTY_COLORS.get(top_party["party"], PARTY_COLOR_OTHER),
        },
    }


def build_temporal_party_distribution_figure(
    records: list[DailyAccountPostCountRecord],
    *,
    compact: bool = False,
) -> go.Figure | None:
    """Return the stacked daily party-video figure, or None when empty."""
    daily_party_counts = aggregate_daily_party_counts(records)
    if not daily_party_counts:
        return None

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

    tick_font = 12 if compact else 20
    body_font = 12 if compact else 25
    hover_font = (
        TEMPORAL_HOVER_FONT_SIZE_COMPACT if compact else TEMPORAL_HOVER_FONT_SIZE
    )
    legend = {
        **TEMPORAL_PARTY_PLOT_LEGEND,
        "font": {"size": 11 if compact else 12},
    }

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
                line=TEMPORAL_AREA_LINE,
                stackgroup="one",
                fillcolor=hex_to_rgba(PARTY_COLORS.get(party, PARTY_COLOR_OTHER)),
                hovertemplate="%{y} Videos<extra></extra>",
                hoverlabel={
                    "bgcolor": TEMPORAL_HOVER_BG,
                    "bordercolor": TEMPORAL_HOVER_BORDER,
                    "font_size": hover_font,
                    "font_family": PLOT_FONT_FAMILY,
                },
            )
        )

    layout: dict[str, Any] = {
        "xaxis_title": "Datum",
        "yaxis_title": "",
        "hovermode": "x unified",
        "dragmode": False,
        "showlegend": True,
        "legend": legend,
        "autosize": True,
        "minreducedwidth": 200 if compact else 500,
        "font": {"size": body_font, "color": "black", "family": PLOT_FONT_FAMILY},
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "margin": {"l": 0, "r": 0, "t": 4 if compact else 0, "b": 0},
        "hoverdistance": 100,
        "hoverlabel": {
            "namelength": 0,
            "bgcolor": TEMPORAL_HOVER_BG,
            "bordercolor": TEMPORAL_HOVER_BORDER,
            "font_size": hover_font,
            "font_family": PLOT_FONT_FAMILY,
        },
    }
    if not compact:
        layout["height"] = TEMPORAL_PLOT_HEIGHT
    fig.update_layout(**layout)

    fig.update_xaxes(
        tickmode="array",
        tickvals=temporal_plot_xaxis_tickvals(all_dates),
        hoverformat="%d.%m.%Y",
        showgrid=True,
        gridwidth=1,
        gridcolor="gray",
        zeroline=True,
        zerolinewidth=1,
        zerolinecolor="gray",
        tickangle=45,
        tickformat="%d.%m",
        tickfont={"size": tick_font, "color": "black"},
        title_font={"size": tick_font},
    )
    fig.update_yaxes(
        automargin=True,
        showgrid=True,
        gridwidth=1,
        gridcolor="gray",
        zeroline=True,
        zerolinewidth=1,
        zerolinecolor="gray",
        tickfont={"size": tick_font, "color": "black"},
        title_font={"size": 1},
        title_standoff=0,
    )
    return fig


def get_temporal_party_distribution_all_accounts(
    records: list[DailyAccountPostCountRecord],
    *,
    compact: bool = False,
) -> dict[str, Any]:
    """Create stacked area chart of posted-video counts per day, across all
    monitored party accounts."""
    fig = build_temporal_party_distribution_figure(records, compact=compact)
    if fig is None:
        return {"html": None}
    return {"html": create_plot_html(fig, config=PLOT_CONFIG)}


def get_total_views_per_party_plot(
    data: list[dict],
    *,
    compact: bool = False,
) -> dict[str, Any]:
    """Horizontal bar chart of total views per party."""
    if not data:
        return {"html": None}

    sorted_data = sorted(data, key=lambda d: d["total_views"])
    parties = [d["party"] for d in sorted_data]
    values = [d["total_views"] for d in sorted_data]
    font_size = _bar_chart_font_size(compact=compact)

    fig = go.Figure(
        go.Bar(
            x=values,
            y=parties,
            orientation="h",
            marker={
                "color": [
                    hex_to_rgba(PARTY_COLORS.get(p, PARTY_COLOR_OTHER)) for p in parties
                ],
                "cornerradius": PLOT_CORNER_RADIUS,
            },
            text=[f"{v:,.0f}" for v in values],
            hovertemplate="<b>%{y}</b>: %{x:,.0f} Views<extra></extra>",
            **_bar_text_kwargs(compact=compact, font_size=font_size, values=values),
        )
    )
    fig.update_layout(
        dragmode=False,
        margin=_bar_chart_margin(compact=compact),
        font={"size": font_size, "color": "black", "family": PLOT_FONT_FAMILY},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis={"visible": False},
        yaxis={"tickfont": {"size": font_size}, "automargin": True},
        **_bar_chart_size_kwargs(compact=compact, n=len(data)),
    )

    return {"html": create_plot_html(fig, config=PLOT_CONFIG)}


def get_views_per_video_per_party_plot(
    data: list[dict],
    *,
    compact: bool = False,
) -> dict[str, Any]:
    """Horizontal bar chart of average views per video per party."""
    if not data:
        return {"html": None}

    sorted_data = sorted(data, key=lambda d: d["avg_views_per_video"])
    parties = [d["party"] for d in sorted_data]
    values = [d["avg_views_per_video"] for d in sorted_data]
    font_size = _bar_chart_font_size(compact=compact)

    fig = go.Figure(
        go.Bar(
            x=values,
            y=parties,
            orientation="h",
            marker={
                "color": [
                    hex_to_rgba(PARTY_COLORS.get(p, PARTY_COLOR_OTHER)) for p in parties
                ],
                "cornerradius": PLOT_CORNER_RADIUS,
            },
            text=[f"{v:,.0f}" for v in values],
            hovertemplate="<b>%{y}</b>: Ø %{x:,.0f} Views/Video<extra></extra>",
            **_bar_text_kwargs(compact=compact, font_size=font_size, values=values),
        )
    )
    fig.update_layout(
        dragmode=False,
        margin=_bar_chart_margin(compact=compact),
        font={"size": font_size, "color": "black", "family": PLOT_FONT_FAMILY},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis={"visible": False},
        yaxis={"tickfont": {"size": font_size}, "automargin": True},
        **_bar_chart_size_kwargs(compact=compact, n=len(data)),
    )

    return {"html": create_plot_html(fig, config=PLOT_CONFIG)}


def get_total_likes_per_party_plot(
    likes_data: list[dict],
    *,
    compact: bool = False,
) -> dict[str, Any]:
    """Horizontal bar chart of total likes per party."""
    if not likes_data:
        return {"html": None}

    parties = [d["party"] for d in reversed(likes_data)]
    values = [d["total_likes"] for d in reversed(likes_data)]
    font_size = _bar_chart_font_size(compact=compact)

    fig = go.Figure(
        go.Bar(
            x=values,
            y=parties,
            orientation="h",
            marker={
                "color": [
                    hex_to_rgba(PARTY_COLORS.get(p, PARTY_COLOR_OTHER)) for p in parties
                ],
                "cornerradius": PLOT_CORNER_RADIUS,
            },
            text=[f"{v:,.0f}" for v in values],
            hovertemplate="<b>%{y}</b>: %{x:,.0f} Likes<extra></extra>",
            **_bar_text_kwargs(compact=compact, font_size=font_size, values=values),
        )
    )
    fig.update_layout(
        dragmode=False,
        margin=_bar_chart_margin(compact=compact),
        font={"size": font_size, "color": "black", "family": PLOT_FONT_FAMILY},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis={"visible": False},
        yaxis={"tickfont": {"size": font_size}, "automargin": True},
        **_bar_chart_size_kwargs(compact=compact, n=len(likes_data)),
    )

    return {"html": create_plot_html(fig, config=PLOT_CONFIG)}


def get_likes_per_video_per_party_plot(
    likes_data: list[dict],
    *,
    compact: bool = False,
) -> dict[str, Any]:
    """Horizontal bar chart of average likes per video per party."""
    if not likes_data:
        return {"html": None}

    sorted_data = sorted(likes_data, key=lambda d: d["avg_likes_per_video"])
    parties = [d["party"] for d in sorted_data]
    values = [d["avg_likes_per_video"] for d in sorted_data]
    font_size = _bar_chart_font_size(compact=compact)

    fig = go.Figure(
        go.Bar(
            x=values,
            y=parties,
            orientation="h",
            marker={
                "color": [
                    hex_to_rgba(PARTY_COLORS.get(p, PARTY_COLOR_OTHER)) for p in parties
                ],
                "cornerradius": PLOT_CORNER_RADIUS,
            },
            text=[f"{v:,.0f}" for v in values],
            hovertemplate="<b>%{y}</b>: Ø %{x:,.0f} Likes/Video<extra></extra>",
            **_bar_text_kwargs(compact=compact, font_size=font_size, values=values),
        )
    )
    fig.update_layout(
        dragmode=False,
        margin=_bar_chart_margin(compact=compact),
        font={"size": font_size, "color": "black", "family": PLOT_FONT_FAMILY},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis={"visible": False},
        yaxis={"tickfont": {"size": font_size}, "automargin": True},
        **_bar_chart_size_kwargs(compact=compact, n=len(sorted_data)),
    )

    return {"html": create_plot_html(fig, config=PLOT_CONFIG)}


def get_tierzeichen_distribution_plot(
    distribution: list[dict],
) -> dict[str, Any]:
    """Horizontal bar chart of TikTok-Tierzeichen counts across participants."""
    if not distribution:
        return {"html": None}

    animals = [d["animal"] for d in reversed(distribution)]
    counts = [d["count"] for d in reversed(distribution)]

    fig = go.Figure(
        go.Bar(
            x=counts,
            y=animals,
            orientation="h",
            marker={
                "color": "#6366f1",
                "cornerradius": PLOT_CORNER_RADIUS,
            },
            text=counts,
            textposition="outside",
            textfont={"size": 16, "family": PLOT_FONT_FAMILY},
            hovertemplate="<b>%{y}</b>: %{x} Teilnehmende<extra></extra>",
        )
    )
    fig.update_layout(
        dragmode=False,
        margin={"t": 10, "l": 10, "r": 40, "b": 10},
        font={"size": 16, "color": "black", "family": PLOT_FONT_FAMILY},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=max(len(distribution) * 60, 200),
        xaxis={"visible": False},
        yaxis={
            "tickfont": {"size": 16},
            "automargin": True,
        },
    )

    return {"html": create_plot_html(fig, config=PLOT_CONFIG)}
