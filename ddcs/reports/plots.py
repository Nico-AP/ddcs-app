import logging
from datetime import date, timedelta
from typing import Any

import plotly.graph_objects as go
from django.conf import settings
from django.templatetags.static import static
from plotly.graph_objs import Figure

from ddcs.reports.config import NO_PARTY_KEY, PARTIES_ORDER, PLOTLY_JS_STATIC_PATH
from ddcs.reports.types import (
    BehaviourComparisonRecord,
    DailyPartyCountRecord,
    PartyCountRecord,
)

logger = logging.getLogger(__name__)


_PARTY_COLOR_OTHER = "#9f9f9f"
PARTY_COLORS = {
    "SPD": "#e4454f",  # "#e3000f",
    "CDU/CSU": "#454545",  # "#000000",
    "Grüne": "#76ae63",  # "#46962b",
    "B90/Grüne": "#76ae63",  # "#46962b",
    "FDP": "#f8eb45",  # "#ffed00",
    "AfD": "#45b4e2",  # "#009ee0",
    "Linke": "#ca6697",  # "#be3075",
    "Sonstige": _PARTY_COLOR_OTHER,  # "#808080",
    "BSW": "#8e5973",  # "#691d42",
    "Keine Partei": "#d4c5aa",
}
PLOT_FONT_FAMILY = "Rubik, Arial, sans-serif"
_RADAR_AXIS_LABEL_FONT_SIZE = 16

# Interactive: toolbar hidden but hover/tooltips enabled.
PLOT_CONFIG = {
    "responsive": True,
    "displayModeBar": False,
    "scrollZoom": False,
    "doubleClick": False,
    "showAxisDragHandles": False,
    "showAxisRangeEntryBoxes": False,
}

# Static: all interaction disabled including hover.
STATIC_PLOT_CONFIG = {
    "responsive": True,
    "displayModeBar": False,
    "staticPlot": True,  # disables all interactions
}

# === Helper functions ===


def _create_plot_html(
    fig: Figure,
    config: dict | None = None,
    *,
    include_plotlyjs: bool = False,
) -> str | None:
    """Helper function to standardize plot HTML generation.

    Plotly.js is loaded once on report pages (see ``reports/base.html``);
    inline figures should not embed another copy.
    """
    plotly_js: bool | str = False
    if include_plotlyjs:
        plotly_js_path = static(PLOTLY_JS_STATIC_PATH)
        if settings.DEBUG:
            import time  # noqa: PLC0415

            version = int(time.time())
            plotly_js_path = f"{plotly_js_path}?v={version}"
        plotly_js = plotly_js_path

    return fig.to_html(
        full_html=False,
        include_plotlyjs=plotly_js,
        config=config or STATIC_PLOT_CONFIG,
    )


def _hex_to_rgba(hex_color: str, alpha: float = 0.9) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


# === Behaviour profile radar ===


def _radar_hover_value_display(metric: str, value_display: str) -> str:
    """Add interpretable units for spider-chart tooltips (table text unchanged)."""
    if metric in (
        "weekend_activity_frac",
        "night_activity_frac",
        "frac_instant_skip",
    ):
        return value_display
    if metric == "avg_watch_per_active_day":
        return f"{value_display}\u00a0Videos"
    if metric == "avg_active_hours_per_day":
        return f"{value_display}\u00a0Stunden"
    if metric == "peak_activity_hour":
        return f"{value_display}\u00a0Uhr"
    return value_display


def get_behaviour_profile_radar(
    comparisons: list[BehaviourComparisonRecord],
) -> dict[str, Any]:
    """Spider chart: percentile scale with mean reference vs. donor profile."""
    if not comparisons:
        return {"html": None}

    categories = [row["radar_label"] for row in comparisons]
    user_r = [row["radar_user"] for row in comparisons]
    mean_r = [row["radar_mean"] for row in comparisons]

    def _close(values: list[float]) -> list[float]:
        return [*values, values[0]]

    def _close_customdata(rows: list[tuple]) -> list[tuple]:
        return [*rows, rows[0]]

    closed_categories = _close(categories)
    closed_user = _close(user_r)
    closed_mean = _close(mean_r)

    user_hover = _close_customdata(
        [
            (
                _radar_hover_value_display(row["metric"], row["value_display"]),
                f"{row['percentile']:.0f}\u00a0%",
            )
            for row in comparisons
        ]
    )
    mean_hover = _close_customdata(
        [
            (
                _radar_hover_value_display(
                    row["metric"], row["reference_mean_display"]
                ),
                f"{row['reference_mean_percentile']:.0f}\u00a0%",
            )
            for row in comparisons
        ]
    )

    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(
            r=closed_mean,
            theta=closed_categories,
            mode="lines+markers",
            name="Durchschnitt",
            marker={"size": 7, "color": "rgba(120, 120, 120, 0.9)"},
            line={"color": "rgba(120, 120, 120, 0.8)", "width": 2.5},
            fillcolor="rgba(150, 150, 150, 0.12)",
            fill="toself",
            customdata=mean_hover,
            hovertemplate=(
                "Mittelwert: %{customdata[0]}<br>"
                "Perzentil: %{customdata[1]}"
                "<extra>Durchschnitt</extra>"
            ),
        )
    )
    fig.add_trace(
        go.Scatterpolar(
            r=closed_user,
            theta=closed_categories,
            mode="lines+markers",
            name="Du",
            marker={"size": 9, "color": "#e4454f"},
            line={"color": "#e4454f", "width": 3.5},
            fillcolor=_hex_to_rgba("#e4454f", 0.22),
            fill="toself",
            customdata=user_hover,
            hovertemplate=(
                "Du: %{customdata[0]}<br>Perzentil: %{customdata[1]}<extra>Du</extra>"
            ),
        )
    )

    fig.update_layout(
        polar={
            "radialaxis": {
                "visible": True,
                "range": [0, 100],
                "showticklabels": False,
                "showline": False,
                "ticks": "",
                "gridcolor": "rgba(0, 0, 0, 0.12)",
            },
            "angularaxis": {
                "tickfont": {
                    "size": _RADAR_AXIS_LABEL_FONT_SIZE,
                    "color": "black",
                    "family": PLOT_FONT_FAMILY,
                },
                "linecolor": "rgba(0, 0, 0, 0.2)",
                "gridcolor": "rgba(0, 0, 0, 0.12)",
            },
            "bgcolor": "rgba(0,0,0,0)",
        },
        showlegend=True,
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": -0.12,
            "xanchor": "center",
            "x": 0.5,
            "font": {"size": 22, "family": PLOT_FONT_FAMILY},
        },
        autosize=True,
        height=620,
        minreducedwidth=500,
        font={"size": 22, "color": "black", "family": PLOT_FONT_FAMILY},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin={"l": 72, "r": 72, "t": 48, "b": 88},
    )

    return {"html": _create_plot_html(fig, config=PLOT_CONFIG)}


# === Party Distribution Plot - User ===


def get_party_distribution_plot_user(
    party_counts: list[PartyCountRecord],
) -> dict[str, Any]:
    """Create party distribution visualization using treemap."""
    relevant_data = [c for c in party_counts if c["party"] != NO_PARTY_KEY]

    if not relevant_data:
        msg = "No party data found for treemap in get_party_distribution_plot_user."
        logger.warning(msg)
        return {"html": None}

    labels = [c["party"] for c in relevant_data]
    values = [c["count"] for c in relevant_data]

    # Create treemap figure.
    fig = go.Figure(
        go.Treemap(
            labels=labels,
            parents=[""] * len(relevant_data),
            values=values,
            textinfo="label+value",
            textfont={"size": 28, "color": "black", "family": PLOT_FONT_FAMILY},
            textposition="middle center",
            hoverinfo="skip",
            text=[
                f"{party}<br>{count} Videos"
                for party, count in zip(labels, values, strict=True)
            ],
            texttemplate="%{text}",
            marker={
                "colors": [
                    _hex_to_rgba(PARTY_COLORS.get(party, _PARTY_COLOR_OTHER))
                    for party in labels
                ]
            },
        )
    )

    # Update layout.
    fig.update_layout(
        title={"y": 0.95, "x": 0.5, "xanchor": "center", "yanchor": "top"},
        font={"size": 12, "color": "black", "family": PLOT_FONT_FAMILY},
        paper_bgcolor="rgba(0,0,0,0)",
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        autosize=True,
        height=450,
        hovermode=False,
    )

    return {"html": _create_plot_html(fig)}


# === Temporal Party Distribution Plot - User ===


def get_temporal_party_distribution_plot_user(
    daily_party_counts: list[DailyPartyCountRecord],
) -> dict:
    """Create weekly watched videos visualization with stacked area chart."""
    relevant_data = [c for c in daily_party_counts if c["party"] != NO_PARTY_KEY]

    if not relevant_data:
        return {"html": None}

    # Build per-party data lookup.
    party_data: dict[str, dict[str, int]] = {}
    for record in relevant_data:
        party_data.setdefault(record["party"], {})[record["date"]] = record["count"]

    # Get all dates
    min_date = min(r["date"] for r in relevant_data)
    max_date = max(r["date"] for r in relevant_data)

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
                fillcolor=_hex_to_rgba(PARTY_COLORS.get(party, _PARTY_COLOR_OTHER)),
                hovertemplate="%{y} Videos<extra></extra>",
                hoverlabel={
                    "bgcolor": "white",
                    "font_size": 16,
                    "font_family": PLOT_FONT_FAMILY,
                },
            )
        )

    legend = {
        "orientation": "h",
        "yanchor": "bottom",
        "y": 1.02,
        "xanchor": "center",
        "x": 0.5,
        "font": {"size": 12},
    }

    fig.update_layout(
        xaxis_title="Datum",
        yaxis_title="Anzahl gesehener Videos (kumulativ)",
        hovermode="x unified",
        dragmode=False,
        showlegend=True,
        legend=legend,
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

    return {"html": _create_plot_html(fig, config=PLOT_CONFIG)}
