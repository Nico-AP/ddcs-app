import logging
from datetime import date, timedelta
from typing import Any

from plotly import graph_objects as go

from ddcs.reports.behaviour_metrics import (
    BEHAVIOUR_CHART_METRICS,
    BEHAVIOUR_CHART_SLIDES,
)
from ddcs.reports.config import NO_PARTY_KEY, PARTIES_ORDER
from ddcs.reports.plots.utils import (
    PARTY_COLOR_OTHER,
    PARTY_COLORS,
    PLOT_CONFIG,
    PLOT_FONT_FAMILY,
    TEMPORAL_PARTY_PLOT_LEGEND,
    create_deferred_plot_html,
    create_plot_html,
    hex_to_rgba,
)
from ddcs.reports.types import (
    BehaviourComparisonRecord,
    DailyPartyCountRecord,
    PartyCountRecord,
)

logger = logging.getLogger(__name__)


_BAR_HALF_HEIGHT = 0.085
_USER_BAR_Y = _BAR_HALF_HEIGHT
_MEAN_BAR_Y = -_BAR_HALF_HEIGHT
_BEHAVIOUR_Y_AXIS_PADDING = 0.07
_BEHAVIOUR_Y_AXIS_RANGE = [
    _MEAN_BAR_Y - _BAR_HALF_HEIGHT - _BEHAVIOUR_Y_AXIS_PADDING,
    _USER_BAR_Y + _BAR_HALF_HEIGHT + _BEHAVIOUR_Y_AXIS_PADDING,
]
_BEHAVIOUR_USER_COLOR = "#0cc4b6"
_BEHAVIOUR_MEAN_COLOR = "#ff587a"
_SINGLE_METRIC_CHART_HEIGHT = 112
_PLOT_CORNER_RADIUS = 4

_FRACTION_METRICS = frozenset(
    {
        "weekend_activity_frac",
        "night_activity_frac",
        "frac_instant_skip",
        "rate_like",
        "frac_political_engagement",
    }
)


def _highlight_user_value(value_display: str) -> str:
    return (
        f'<span style="color: {_BEHAVIOUR_USER_COLOR}; font-weight: 600;">'
        f"{value_display}</span>"
    )


def _highlight_mean_value(value_display: str) -> str:
    return (
        f'<span style="color: {_BEHAVIOUR_MEAN_COLOR}; font-weight: 600;">'
        f"{value_display}</span>"
    )


_USER_SUBTITLE_SENTENCES: dict[str, str] = {
    "avg_session_length_sec": ("Deine TikTok-Sessions dauern im Schnitt {value}."),
    "avg_videos_per_session": ("Pro Session schaust du im Schnitt {value} Videos."),
    "avg_active_hours_per_day": (
        "An Tagen, an denen du TikTok nutzt, bist du im Schnitt {value} Stunden aktiv."
    ),
    "weekend_activity_frac": (
        "{value} deiner TikTok-Zeit verbringst du am Wochenende."
    ),
    "night_activity_frac": ("{value} deiner Videos schaust du nachts (22-6 Uhr)."),
    "peak_activity_hour": (
        "Deine aktivste Stunde ist {hour}. "
        "{same_frac} der Teilnehmenden nutzen TikTok am häufigsten "
        "zur gleichen Stunde, {other_frac} zu einer anderen Uhrzeit."
    ),
    "frac_instant_skip": ("Bei {value} der Videos scrollst du direkt weiter."),
    "rate_like": ("{value} der Videos, die du anschaust, likst du."),
    "frac_political_engagement": (
        "{value} deiner Interaktionen (Likes, Shares, Speichern, Kommentare) "
        "betreffen politische Inhalte."
    ),
}


def _row_user_sentence(row: BehaviourComparisonRecord) -> str:
    if row["metric"] == "peak_activity_hour":
        template = _USER_SUBTITLE_SENTENCES[row["metric"]]
        hour = _highlight_user_value(row["value_display"])
        same_frac = _highlight_user_value(
            row.get("chart_user_value_display", row["value_display"])
        )
        other_frac = _highlight_mean_value(
            row.get("chart_reference_value_display", row["reference_mean_display"])
        )
        return template.format(hour=hour, same_frac=same_frac, other_frac=other_frac)

    template = _USER_SUBTITLE_SENTENCES.get(
        row["metric"],
        "Dein Wert: {value}",
    )
    highlighted = _highlight_user_value(row["value_display"])
    return template.format(value=highlighted)


def _row_title_text(row: BehaviourComparisonRecord) -> str:
    return _row_user_sentence(row)


def _add_bar_end_label(
    fig: go.Figure,
    x_end: float,
    y_center: float,
    label: str,
    color: str,
) -> None:
    fig.add_annotation(
        x=x_end,
        y=y_center,
        text=label,
        showarrow=False,
        xanchor="left",
        xshift=6,
        font={"color": color, "size": 12, "family": PLOT_FONT_FAMILY},
        xref="x",
        yref="y",
    )


def _behaviour_hover_value_display(metric: str, value_display: str) -> str:
    if metric in _FRACTION_METRICS:
        return value_display
    if metric == "avg_session_length_sec":
        return value_display
    if metric == "avg_videos_per_session":
        return f"{value_display}\u00a0Videos"
    if metric == "avg_active_hours_per_day":
        return f"{value_display}\u00a0Stunden"
    return value_display


def _comparison_chart_values(
    row: BehaviourComparisonRecord,
) -> tuple[float, float, str, str]:
    if row["metric"] == "peak_activity_hour":
        return (
            row.get("chart_user_value", row["value"]),
            row.get("chart_reference_value", row["reference_mean"]),
            row.get("chart_user_value_display", row["value_display"]),
            row.get("chart_reference_value_display", row["reference_mean_display"]),
        )
    return (
        row["value"],
        row["reference_mean"],
        row["value_display"],
        row["reference_mean_display"],
    )


def _metric_axis_max(
    user_value: float,
    mean_value: float,
    *,
    user_display: str,
    mean_display: str,
) -> float:
    """X-axis upper bound with room for end labels to the right of the bars."""
    data_max = max(user_value, mean_value)
    if data_max <= 0:
        data_max = 1.0

    longest_label = max(len(user_display), len(mean_display))
    label_fraction = max(0.22, longest_label * 0.065)
    return data_max * (1.0 + label_fraction)


def _add_horizontal_value_bar(
    fig: go.Figure,
    x_end: float,
    y_center: float,
    color: str,
) -> None:
    if x_end <= 0:
        return
    fig.add_trace(
        go.Bar(
            x=[x_end],
            y=[y_center],
            orientation="h",
            width=_BAR_HALF_HEIGHT * 2,
            marker={"color": color},
            showlegend=False,
            hoverinfo="skip",
        )
    )


def _add_metric_value_bars(
    fig: go.Figure,
    user_value: float,
    mean_value: float,
) -> None:
    _add_horizontal_value_bar(fig, user_value, _USER_BAR_Y, _BEHAVIOUR_USER_COLOR)
    _add_horizontal_value_bar(fig, mean_value, _MEAN_BAR_Y, _BEHAVIOUR_MEAN_COLOR)


def _behaviour_value_xaxis(axis_max: float) -> dict[str, Any]:
    return {
        "range": [0, axis_max],
        "fixedrange": True,
        "showticklabels": False,
        "showgrid": True,
        "gridcolor": "rgba(0, 0, 0, 0.08)",
        "zeroline": False,
    }


def _behaviour_user_hover_data(
    row: BehaviourComparisonRecord,
) -> tuple[str, str, str]:
    if row["metric"] == "peak_activity_hour":
        return (
            "Gleiche Peak-Stunde",
            row.get("chart_user_value_display", row["value_display"]),
            f"Deine Peak-Stunde: {row['value_display']}",
        )
    return (
        row["label"],
        _behaviour_hover_value_display(row["metric"], row["value_display"]),
        f"{round(row['percentile'])}. Perzentil",
    )


def _behaviour_mean_hover_data(row: BehaviourComparisonRecord) -> tuple[str, str]:
    if row["metric"] == "peak_activity_hour":
        return (
            "Andere Peak-Stunde",
            row.get("chart_reference_value_display", row["reference_mean_display"]),
        )
    return (
        "Durchschnitt Teilnehmende",
        row["reference_mean_display"],
    )


def _build_single_metric_chart(row: BehaviourComparisonRecord) -> str | None:
    user_value, mean_value, user_display, mean_display = _comparison_chart_values(row)
    axis_max = _metric_axis_max(
        user_value,
        mean_value,
        user_display=user_display,
        mean_display=mean_display,
    )

    fig = go.Figure()
    _add_metric_value_bars(fig, user_value, mean_value)
    _add_bar_end_label(
        fig, user_value, _USER_BAR_Y, user_display, _BEHAVIOUR_USER_COLOR
    )
    _add_bar_end_label(
        fig,
        mean_value,
        _MEAN_BAR_Y,
        mean_display,
        _BEHAVIOUR_MEAN_COLOR,
    )

    user_hover_x = user_value / 2 if user_value > 0 else 0
    mean_hover_x = mean_value / 2 if mean_value > 0 else 0

    fig.add_trace(
        go.Scatter(
            x=[user_hover_x],
            y=[_USER_BAR_Y],
            mode="markers",
            name="Du",
            marker={
                "size": 24,
                "color": "rgba(0, 0, 0, 0)",
                "line": {"width": 0},
            },
            customdata=[_behaviour_user_hover_data(row)],
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "Dein Wert: %{customdata[1]}<br>"
                "%{customdata[2]}"
                "<extra></extra>"
            ),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[mean_hover_x],
            y=[_MEAN_BAR_Y],
            mode="markers",
            name="Durchschnitt",
            marker={
                "size": 24,
                "color": "rgba(0, 0, 0, 0)",
                "line": {"width": 0},
            },
            customdata=[_behaviour_mean_hover_data(row)],
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>Wert: %{customdata[1]}<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        xaxis=_behaviour_value_xaxis(axis_max),
        yaxis={
            "showticklabels": False,
            "showgrid": False,
            "zeroline": False,
            "range": _BEHAVIOUR_Y_AXIS_RANGE,
            "fixedrange": True,
        },
        dragmode=False,
        showlegend=False,
        autosize=True,
        width=None,
        height=_SINGLE_METRIC_CHART_HEIGHT,
        font={"size": 13, "color": "black", "family": PLOT_FONT_FAMILY},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin={"l": 8, "r": 8, "t": 2, "b": 4},
        hovermode="closest",
        barcornerradius=_PLOT_CORNER_RADIUS,
    )
    return create_deferred_plot_html(fig, config=PLOT_CONFIG)


def get_behaviour_profile_rows(
    comparisons: list[BehaviourComparisonRecord],
) -> list[dict[str, str]]:
    """One mini-chart and colloquial title per behaviour chart metric."""
    if not comparisons:
        return []

    by_metric = {row["metric"]: row for row in comparisons}
    chart_rows = [
        by_metric[metric] for metric in BEHAVIOUR_CHART_METRICS if metric in by_metric
    ]
    return [_behaviour_profile_row(row) for row in chart_rows]


def get_behaviour_profile_slides(
    comparisons: list[BehaviourComparisonRecord],
) -> list[dict[str, list[dict[str, str]]]]:
    """Behaviour charts grouped into carousel slides."""
    if not comparisons:
        return []

    by_metric = {row["metric"]: row for row in comparisons}
    slides: list[dict[str, list[dict[str, str]]]] = []
    for slide_metrics in BEHAVIOUR_CHART_SLIDES:
        rows = [
            _behaviour_profile_row(by_metric[metric])
            for metric in slide_metrics
            if metric in by_metric
        ]
        if rows:
            slides.append({"rows": rows})
    return slides


def _behaviour_profile_row(row: BehaviourComparisonRecord) -> dict[str, str]:
    return {
        "chart_html": _build_single_metric_chart(row),
        "title_html": _row_title_text(row),
    }


def get_behaviour_profile_comparison(
    comparisons: list[BehaviourComparisonRecord],
) -> dict[str, Any]:
    """Deprecated wrapper kept for tests; prefer ``get_behaviour_profile_rows``."""
    rows = get_behaviour_profile_rows(comparisons)
    if not rows:
        return {"html": None}
    return {"html": rows[0]["chart_html"]}


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
                    hex_to_rgba(PARTY_COLORS.get(party, PARTY_COLOR_OTHER))
                    for party in labels
                ],
                "cornerradius": _PLOT_CORNER_RADIUS,
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

    return {"html": create_plot_html(fig)}


def get_temporal_party_distribution_plot_user(
    daily_party_counts: list[DailyPartyCountRecord],
) -> dict:
    """Create daily watched videos visualization with stacked bar chart."""
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
        barcornerradius=_PLOT_CORNER_RADIUS,
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
