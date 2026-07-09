import json
import uuid

from django.conf import settings
from django.templatetags.static import static
from plotly.graph_objs import Figure

from ddcs.reports.config import PLOTLY_JS_STATIC_PATH

PARTY_COLOR_OTHER = "#9f9f9f"

# TODO: Clean this up
PARTY_COLORS = {
    "SPD": "#e4454f",  # "#e3000f",
    "CDU/CSU": "#454545",  # "#000000",
    "CDU": "#454545",  # "#000000",
    "CSU": "#454545",  # "#000000",
    "Grüne": "#83b672",  # "#46962b",
    "B90/Grüne": "#83b672",  # "#46962b",
    "B90/GRÜNE": "#83b672",  # "#46962b",
    "FDP": "#f8eb45",  # "#ffed00",
    "AfD": "#45b4e2",  # "#009ee0",
    "LINKE": "#ca6697",  # "#be3075",
    "Linke": "#ca6697",  # "#be3075",
    "Sonstige": PARTY_COLOR_OTHER,  # "#808080",
    "BSW": "#8e5973",  # "#691d42",
    "Keine Partei": "#d4c5aa",
}
PLOT_FONT_FAMILY = "Rubik, Arial, sans-serif"
PLOT_CORNER_RADIUS = 4
TEMPORAL_PARTY_PLOT_LEGEND = {
    "orientation": "h",
    "yanchor": "bottom",
    "y": 1.02,
    "xanchor": "center",
    "x": 0.5,
    "font": {"size": 12},
}
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


def create_plot_html(
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


def create_deferred_plot_html(
    fig: Figure,
    config: dict | None = None,
    *,
    mount_class: str = "behaviour-plot-mount",
) -> str | None:
    """Emit a mount point plus JSON spec for client-side ``Plotly.newPlot``.

    Behaviour mini-charts sit inside a Bootstrap carousel and HTMX swaps;
    inline ``Plotly.newPlot`` runs before the container has its final width
    (or while slides are ``display: none``), so bar lengths are wrong until
    the user interacts. Initialise from ``behaviour-profile-filters.js`` instead.
    """
    plot_id = f"behaviour-plot-{uuid.uuid4().hex}"
    figure = json.loads(fig.to_json())
    height = figure.get("layout", {}).get("height") or 128
    payload = json.dumps(
        {
            "data": figure.get("data", []),
            "layout": figure.get("layout", {}),
            "config": config or PLOT_CONFIG,
        },
        separators=(",", ":"),
    )
    return (
        f'<div id="{plot_id}" class="{mount_class}" '
        f'style="height:{height}px; width:100%;"></div>'
        f'<script type="application/json" class="behaviour-plot-spec" '
        f'data-target="{plot_id}">{payload}</script>'
    )


def hex_to_rgba(hex_color: str, alpha: float = 0.9) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"
