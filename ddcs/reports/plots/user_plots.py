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
    TEMPORAL_AREA_LINE,
    TEMPORAL_PARTY_PLOT_LEGEND,
    TEMPORAL_PLOT_HEIGHT,
    create_deferred_plot_html,
    create_plot_html,
    hex_to_rgba,
    temporal_plot_xaxis_tickvals,
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
# Darker on-brand text (matches --text-accent / --text-accent-alt).
_BEHAVIOUR_USER_TEXT_COLOR = "#058076"
_BEHAVIOUR_MEAN_TEXT_COLOR = "#b3004e"
_SINGLE_METRIC_CHART_HEIGHT = 112
# Ridge + companion bar should match a three-bar slide: ridge takes two chart slots.
_RIDGE_CHART_HEIGHT = _SINGLE_METRIC_CHART_HEIGHT * 2
_PLOT_CORNER_RADIUS = 4
_HOURS = list(range(24))
_PEAK_HOUR_TICK_HOURS = [0, 6, 12, 18, 23]
_WEEKDAYS = list(range(7))
_WEEKDAY_TICK_LABELS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
_HOURS_PER_DAY = len(_HOURS)
_WEEKDAYS_PER_WEEK = len(_WEEKDAYS)

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
        f'<span style="color: {_BEHAVIOUR_USER_TEXT_COLOR}; font-weight: 600;">'
        f"{value_display}</span>"
    )


def _highlight_mean_value(value_display: str) -> str:
    return (
        f'<span style="color: {_BEHAVIOUR_MEAN_TEXT_COLOR}; font-weight: 600;">'
        f"{value_display}</span>"
    )


_USER_SUBTITLE_SENTENCES: dict[str, str] = {
    "avg_session_length_sec": ("Deine TikTok-Sessions dauern im Schnitt {value}."),
    "avg_videos_per_session": ("Pro Session schaust du im Schnitt {value} Videos."),
    "avg_active_hours_per_day": (
        "An Tagen, an denen du TikTok nutzt, bist du im Schnitt {value} Stunden aktiv."
    ),
    "weekend_activity_frac": (
        "Das heißt, {value} deiner TikTok-Zeit verbringst du am Wochenende."
    ),
    "night_activity_frac": (
        "Das heißt, {value} deiner Videos schaust du nachts (22-6 Uhr)."
    ),
    "peak_activity_hour": (
        "So viele Videos schaust "
        '<span style="color: {_user}; font-weight: 600;">Du</span> '
        "über den Tag im Durchschnitt im Vergleich zu "
        '<span style="color: {_mean}; font-weight: 600;">Anderen</span>.'
    ),
    "weekday_active_hours": (
        "So viele Stunden bist "
        '<span style="color: {_user}; font-weight: 600;">Du</span> '
        "an den Wochentagen im Schnitt aktiv im Vergleich zu "
        '<span style="color: {_mean}; font-weight: 600;">Anderen</span>.'
    ),
    "frac_instant_skip": ("Bei {value} der Videos scrollst du direkt weiter."),
    "rate_like": ("{value} der Videos, die du anschaust, likst du."),
    "frac_political_engagement": (
        "{value} deiner Interaktionen (Likes, Shares, Speichern, Kommentare) "
        "betreffen politische Inhalte."
    ),
}


def _row_user_sentence(row: BehaviourComparisonRecord) -> str:
    if row["metric"] in {"peak_activity_hour", "weekday_active_hours"}:
        template = _USER_SUBTITLE_SENTENCES[row["metric"]]
        return template.format(
            _user=_BEHAVIOUR_USER_TEXT_COLOR,
            _mean=_BEHAVIOUR_MEAN_TEXT_COLOR,
        )

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


def _series_argmax(series: list[float]) -> int:
    return max(range(len(series)), key=lambda index: series[index])


def _add_ridge_max_label(
    fig: go.Figure,
    *,
    series: list[float],
    x_values: list[int],
    color: str,
    xshift: int = 0,
) -> None:
    if not series or max(series) <= 0:
        return
    peak_index = _series_argmax(series)
    fig.add_annotation(
        x=x_values[peak_index],
        y=series[peak_index],
        text=f"{series[peak_index]:.0f}",
        showarrow=False,
        xshift=xshift,
        yshift=12,
        xanchor="center",
        yanchor="bottom",
        font={"color": color, "size": 12, "family": PLOT_FONT_FAMILY},
    )


def _build_dual_ridge_chart(  # noqa: PLR0913
    *,
    user_series: list[float],
    reference_series: list[float] | None,
    x_values: list[int],
    tick_vals: list[int],
    tick_text: list[str],
    point_labels: list[str],
    value_unit: str,
    marker_x: int | None = None,
) -> str | None:
    """Filled dual ridge (user + optional reference) for behaviour slides."""
    if not user_series or len(point_labels) != len(user_series):
        return None

    has_reference = bool(reference_series and len(reference_series) == len(user_series))
    series_values = list(user_series)
    if has_reference and reference_series is not None:
        series_values.extend(reference_series)
    series_max = max(series_values)
    y_max = series_max if series_max > 0 else 1.0

    hover_rows: list[list[str | float]] = []
    for index, label in enumerate(point_labels):
        user_value = user_series[index]
        if has_reference and reference_series is not None:
            hover_rows.append([label, user_value, reference_series[index]])
        else:
            hover_rows.append([label, user_value])

    fig = go.Figure()
    if has_reference and reference_series is not None:
        fig.add_trace(
            go.Scatter(
                x=x_values,
                y=reference_series,
                mode="lines",
                name="Andere",
                line={
                    "width": 1.5,
                    "color": _BEHAVIOUR_MEAN_COLOR,
                    "shape": "spline",
                    "smoothing": 0.6,
                },
                fill="tozeroy",
                fillcolor=hex_to_rgba(_BEHAVIOUR_MEAN_COLOR, alpha=0.22),
                hoverinfo="skip",
            )
        )
    fig.add_trace(
        go.Scatter(
            x=x_values,
            y=user_series,
            mode="lines",
            name="Du",
            line={
                "width": 1.5,
                "color": _BEHAVIOUR_USER_COLOR,
                "shape": "spline",
                "smoothing": 0.6,
            },
            fill="tozeroy",
            fillcolor=hex_to_rgba(_BEHAVIOUR_USER_COLOR, alpha=0.35),
            hoverinfo="skip",
        )
    )
    if marker_x is not None and 0 <= marker_x < len(user_series):
        fig.add_trace(
            go.Scatter(
                x=[marker_x],
                y=[user_series[marker_x]],
                mode="markers",
                name="Peak",
                marker={
                    "size": 9,
                    "color": _BEHAVIOUR_USER_TEXT_COLOR,
                    "line": {"width": 1.5, "color": "white"},
                },
                hoverinfo="skip",
                showlegend=False,
            )
        )

    user_xshift = 0
    reference_xshift = 0
    if has_reference and reference_series is not None:
        user_peak = _series_argmax(user_series)
        reference_peak = _series_argmax(reference_series)
        if abs(user_peak - reference_peak) <= 1:
            user_xshift = -10
            reference_xshift = 10
        _add_ridge_max_label(
            fig,
            series=reference_series,
            x_values=x_values,
            color=_BEHAVIOUR_MEAN_TEXT_COLOR,
            xshift=reference_xshift,
        )
    _add_ridge_max_label(
        fig,
        series=user_series,
        x_values=x_values,
        color=_BEHAVIOUR_USER_TEXT_COLOR,
        xshift=user_xshift,
    )

    if has_reference:
        hovertemplate = (
            "<b>%{customdata[0]}</b><br>"
            f"Du: %{{customdata[1]:.2f}} {value_unit}<br>"
            f"Andere: %{{customdata[2]:.2f}} {value_unit}"
            "<extra></extra>"
        )
    else:
        hovertemplate = (
            "<b>%{customdata[0]}</b><br>"
            f"Du: %{{customdata[1]:.2f}} {value_unit}"
            "<extra></extra>"
        )

    fig.add_trace(
        go.Scatter(
            x=x_values,
            y=user_series,
            mode="markers",
            name="hover",
            marker={
                "size": 14,
                "color": "rgba(0, 0, 0, 0)",
                "line": {"width": 0},
            },
            customdata=hover_rows,
            hovertemplate=hovertemplate,
            showlegend=False,
        )
    )

    fig.update_layout(
        xaxis={
            "title": "",
            "range": [x_values[0] - 0.5, x_values[-1] + 0.5],
            "tickmode": "array",
            "tickvals": tick_vals,
            "ticktext": tick_text,
            "fixedrange": True,
            "automargin": False,
            "showgrid": False,
            "zeroline": False,
            "tickfont": {"size": 11, "color": "black"},
        },
        yaxis={
            "title": "",
            "range": [0, y_max * 1.28],
            "fixedrange": True,
            "automargin": False,
            "showticklabels": True,
            "ticks": "",
            "ticklabelposition": "inside",
            "nticks": 4,
            "tickformat": ".0f",
            "tickfont": {"size": 11, "color": "black"},
            "showgrid": False,
            "zeroline": False,
        },
        dragmode=False,
        showlegend=has_reference,
        legend={
            "orientation": "h",
            "x": 0.5,
            "xanchor": "center",
            "y": 1.1,
            "yanchor": "bottom",
            "font": {"size": 11},
        },
        autosize=True,
        width=None,
        height=_RIDGE_CHART_HEIGHT,
        font={"size": 13, "color": "black", "family": PLOT_FONT_FAMILY},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin={"l": 8, "r": 8, "t": 4, "b": 28},
        hovermode="closest",
    )
    return create_deferred_plot_html(fig, config=PLOT_CONFIG)


def _build_peak_hour_ridge_chart(row: BehaviourComparisonRecord) -> str | None:
    """Ridge-style density of mean videos watched per clock hour."""
    hourly = row.get("hourly_watch_means")
    if not hourly or len(hourly) != _HOURS_PER_DAY:
        return None
    return _build_dual_ridge_chart(
        user_series=hourly,
        reference_series=row.get("reference_hourly_watch_means"),
        x_values=_HOURS,
        tick_vals=_PEAK_HOUR_TICK_HOURS,
        tick_text=[f"{hour}:00" for hour in _PEAK_HOUR_TICK_HOURS],
        point_labels=[f"{hour}:00 Uhr" for hour in _HOURS],
        value_unit="Videos (⌀)",
        marker_x=round(row["value"]),
    )


def _build_weekday_active_hours_ridge_chart(
    row: BehaviourComparisonRecord,
) -> str | None:
    """Ridge-style density of mean active hours by weekday."""
    weekdays = row.get("weekday_active_hours")
    if not weekdays or len(weekdays) != _WEEKDAYS_PER_WEEK:
        return None
    return _build_dual_ridge_chart(
        user_series=weekdays,
        reference_series=row.get("reference_weekday_active_hours"),
        x_values=_WEEKDAYS,
        tick_vals=_WEEKDAYS,
        tick_text=_WEEKDAY_TICK_LABELS,
        point_labels=_WEEKDAY_TICK_LABELS,
        value_unit="aktive Stunden (⌀)",
    )


def _build_single_metric_chart(row: BehaviourComparisonRecord) -> str | None:
    if row["metric"] == "peak_activity_hour":
        ridge = _build_peak_hour_ridge_chart(row)
        if ridge is not None:
            return ridge
    if row["metric"] == "weekday_active_hours":
        ridge = _build_weekday_active_hours_ridge_chart(row)
        if ridge is not None:
            return ridge

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
        fig, user_value, _USER_BAR_Y, user_display, _BEHAVIOUR_USER_TEXT_COLOR
    )
    _add_bar_end_label(
        fig,
        mean_value,
        _MEAN_BAR_Y,
        mean_display,
        _BEHAVIOUR_MEAN_TEXT_COLOR,
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
) -> list[dict[str, str | None]]:
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
) -> list[dict[str, list[dict[str, str | None]]]]:
    """Behaviour charts grouped into carousel slides."""
    if not comparisons:
        return []

    by_metric = {row["metric"]: row for row in comparisons}
    slides: list[dict[str, list[dict[str, str | None]]]] = []
    for slide_metrics in BEHAVIOUR_CHART_SLIDES:
        rows = [
            _behaviour_profile_row(by_metric[metric])
            for metric in slide_metrics
            if metric in by_metric
        ]
        if rows:
            slides.append({"rows": rows})
    return slides


def _behaviour_profile_row(row: BehaviourComparisonRecord) -> dict[str, str | None]:
    return {
        "metric": row["metric"],
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


def _temporal_party_series(
    daily_party_counts: list[DailyPartyCountRecord],
) -> tuple[list[str], dict[str, dict[str, int]]] | None:
    """Dates and per-party daily counts, excluding non-party political videos."""
    relevant_data = [c for c in daily_party_counts if c["party"] != NO_PARTY_KEY]
    if not relevant_data:
        return None

    party_data: dict[str, dict[str, int]] = {}
    for record in relevant_data:
        party_data.setdefault(record["party"], {})[record["date"]] = record["count"]

    min_date = min(r["date"] for r in relevant_data)
    max_date = max(r["date"] for r in relevant_data)
    start = date.fromisoformat(min_date)
    end = date.fromisoformat(max_date)
    all_dates = [
        (start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)
    ]
    return all_dates, party_data


def _apply_temporal_party_axes(fig: go.Figure, all_dates: list[str]) -> None:
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


def _temporal_party_layout() -> dict[str, Any]:
    return {
        "xaxis_title": "Datum",
        "yaxis_title": "",
        "hovermode": "x unified",
        "dragmode": False,
        "showlegend": True,
        "legend": TEMPORAL_PARTY_PLOT_LEGEND,
        "autosize": True,
        "height": TEMPORAL_PLOT_HEIGHT,
        "minreducedwidth": 500,
        "font": {"size": 25, "color": "black", "family": PLOT_FONT_FAMILY},
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "margin": {"l": 0, "r": 0, "t": 0, "b": 0},
        "hoverdistance": 100,
        "hoverlabel": {"namelength": 0},
    }


def get_temporal_party_distribution_plot_user(
    daily_party_counts: list[DailyPartyCountRecord],
) -> dict:
    """Create daily watched videos visualization with stacked area chart."""
    series = _temporal_party_series(daily_party_counts)
    if series is None:
        return {"html": None}

    all_dates, party_data = series
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
                    "bgcolor": "white",
                    "font_size": 16,
                    "font_family": PLOT_FONT_FAMILY,
                },
            )
        )

    fig.update_layout(**_temporal_party_layout())
    _apply_temporal_party_axes(fig, all_dates)
    return {"html": create_plot_html(fig, config=PLOT_CONFIG)}
