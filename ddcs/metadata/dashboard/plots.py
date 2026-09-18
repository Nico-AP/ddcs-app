"""Plotly figure builders for the internal metadata dashboard.

Reuses the shared styling constants and HTML-embedding helper from
``ddcs.reports.plots.utils`` so this page looks consistent with the rest of
the project, even though it lives in a different app.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from plotly import graph_objects as go

from ddcs.reports.plots.utils import (
    PLOT_CONFIG,
    PLOT_CORNER_RADIUS,
    PLOT_FONT_FAMILY,
    create_plot_html,
)

if TYPE_CHECKING:
    from ddcs.metadata.dashboard.metrics import (
        ClassificationCoverageDay,
        OriginCount,
        SyncCoverageDay,
    )

_ORIGIN_BAR_HEIGHT = 320
_COVERAGE_BAR_HEIGHT = 320
_WITH_INFO_COLOR = "#2f7d5f"
_WITHOUT_INFO_COLOR = "#c8543c"
_SUCCEEDED_COLOR = "#2f7d5f"
_ATTEMPTED_COLOR = "#c9a227"
_MONITORED_LINE_COLOR = "#454545"
_TOTAL_COLOR = "#9f9f9f"
_CLASSIFIED_COLOR = "#6366f1"

_SHARED_LAYOUT: dict[str, Any] = {
    "dragmode": False,
    "font": {"size": 13, "color": "black", "family": PLOT_FONT_FAMILY},
    "paper_bgcolor": "rgba(0,0,0,0)",
    "plot_bgcolor": "rgba(0,0,0,0)",
    "margin": {"t": 10, "l": 10, "r": 10, "b": 10},
    "legend": {"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
}


def get_origin_counts_plot(origin_counts: list[OriginCount]) -> dict[str, Any]:
    """Grouped bar chart: one group per DataOrigin, with/without API info."""
    if not origin_counts:
        return {"html": None}

    origins = [row["added_by"] for row in origin_counts]
    fig = go.Figure(
        data=[
            go.Bar(
                name="With API info",
                x=origins,
                y=[row["with_api_info"] for row in origin_counts],
                marker={"color": _WITH_INFO_COLOR, "cornerradius": PLOT_CORNER_RADIUS},
            ),
            go.Bar(
                name="Without API info",
                x=origins,
                y=[row["without_api_info"] for row in origin_counts],
                marker={
                    "color": _WITHOUT_INFO_COLOR,
                    "cornerradius": PLOT_CORNER_RADIUS,
                },
            ),
        ]
    )
    fig.update_layout(
        **_SHARED_LAYOUT,
        barmode="stack",
        height=_ORIGIN_BAR_HEIGHT,
        yaxis={"title": "Videos", "automargin": True},
    )
    return {"html": create_plot_html(fig, config=PLOT_CONFIG)}


def get_sync_coverage_plot(
    coverage: list[SyncCoverageDay], *, monitored_count: int
) -> dict[str, Any]:
    """Daily succeeded/attempted sync counts, with a monitored-count reference line."""
    if not coverage:
        return {"html": None}

    dates = [day["date"].isoformat() for day in coverage]
    fig = go.Figure(
        data=[
            go.Bar(
                name="Attempted",
                x=dates,
                y=[day["attempted"] for day in coverage],
                marker={"color": _ATTEMPTED_COLOR, "cornerradius": PLOT_CORNER_RADIUS},
            ),
            go.Bar(
                name="Succeeded",
                x=dates,
                y=[day["succeeded"] for day in coverage],
                marker={"color": _SUCCEEDED_COLOR, "cornerradius": PLOT_CORNER_RADIUS},
            ),
        ]
    )
    fig.update_layout(
        **_SHARED_LAYOUT,
        barmode="overlay",
        height=_COVERAGE_BAR_HEIGHT,
        yaxis={"title": "Items synced", "automargin": True},
        xaxis={"tickangle": 45},
    )
    if monitored_count:
        fig.add_hline(
            y=monitored_count,
            line={"color": _MONITORED_LINE_COLOR, "dash": "dash", "width": 1},
            annotation_text=f"Monitored: {monitored_count}",
            annotation_position="top left",
        )
    return {"html": create_plot_html(fig, config=PLOT_CONFIG)}


def get_classification_coverage_plot(
    coverage: list[ClassificationCoverageDay],
) -> dict[str, Any]:
    """Daily classified-vs-total (has API info) video counts."""
    if not coverage:
        return {"html": None}

    dates = [day["date"].isoformat() for day in coverage]
    fig = go.Figure(
        data=[
            go.Scatter(
                name="Has API info",
                x=dates,
                y=[day["total"] for day in coverage],
                mode="lines",
                line={"color": _TOTAL_COLOR, "width": 2},
            ),
            go.Scatter(
                name="Classified",
                x=dates,
                y=[day["classified"] for day in coverage],
                mode="lines",
                line={"color": _CLASSIFIED_COLOR, "width": 2},
                fill="tonexty",
                fillcolor="rgba(99, 102, 241, 0.15)",
            ),
        ]
    )
    fig.update_layout(
        **_SHARED_LAYOUT,
        height=_COVERAGE_BAR_HEIGHT,
        yaxis={"title": "Videos", "automargin": True},
        xaxis={"tickangle": 45},
        hovermode="x unified",
    )
    return {"html": create_plot_html(fig, config=PLOT_CONFIG)}
