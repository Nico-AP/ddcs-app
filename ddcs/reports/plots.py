import logging
from datetime import date, timedelta
from typing import Any

import plotly.graph_objects as go
from django.conf import settings
from django.templatetags.static import static
from plotly.graph_objs import Figure

from ddcs.reports.config import NO_PARTY_KEY, PARTIES_ORDER, PLOTLY_JS_STATIC_PATH
from ddcs.reports.types import DailyPartyCountRecord, PartyCountRecord

logger = logging.getLogger(__name__)


PARTY_COLORS = {
    "SPD": "#e4454f",  # "#e3000f",
    "CDU/CSU": "#454545",  # "#000000",
    "Grüne": "#76ae63",  # "#46962b",
    "FDP": "#f8eb45",  # "#ffed00",
    "AfD": "#45b4e2",  # "#009ee0",
    "Linke": "#ca6697",  # "#be3075",
    "Sonstige": "#9f9f9f",  # "#808080",
    "BSW": "#8e5973",  # "#691d42",
    "Keine Partei": "#d4c5aa",
}
PLOT_FONT_FAMILY = "Rubik, Arial, sans-serif"

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


def _create_plot_html(fig: Figure, config: dict | None = None) -> str | None:
    """Helper function to standardize plot HTML generation."""
    plotly_js_path = static(PLOTLY_JS_STATIC_PATH)

    # Add version parameter only in debug/development mode
    if settings.DEBUG:
        import time  # noqa: PLC0415

        version = int(time.time())
        plotly_js_path = f"{plotly_js_path}?v={version}"

    return fig.to_html(
        full_html=False,
        include_plotlyjs=plotly_js_path,
        config=config or STATIC_PLOT_CONFIG,
    )


def _hex_to_rgba(hex_color: str, alpha: float = 0.9) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


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
            marker={"colors": [_hex_to_rgba(PARTY_COLORS[party]) for party in labels]},
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
                fillcolor=_hex_to_rgba(PARTY_COLORS[party]),
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
