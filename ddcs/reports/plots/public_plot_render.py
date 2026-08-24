"""Headless chart rendering for the embeddable public-plot PNGs.

The interactive site charts are Plotly, but rasterising those server-side
would require a real Chrome install (Kaleido >= 1.0). These embed images are
therefore redrawn with Matplotlib's Agg backend, which needs no browser and
is already available via ``wordcloud``. Colours and stacking order are kept
in sync with ``public_plots.py`` so the exported image reads like the site.
"""

from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import TYPE_CHECKING, Any

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import FancyBboxPatch

from ddcs.reports.config import PARTIES_ORDER
from ddcs.reports.metrics.account_metrics import (
    aggregate_daily_party_counts,
    aggregate_party_counts,
)
from ddcs.reports.plots.utils import (
    PARTY_COLOR_OTHER,
    PARTY_COLORS,
    temporal_plot_xaxis_tickvals,
)

if TYPE_CHECKING:
    from ddcs.reports.types import DailyAccountPostCountRecord

PLOT_WIDTH_PX = 1200
PLOT_HEIGHT_PX = 560
PLOT_DPI = 200

_AREA_ALPHA = 0.9
_GRID_COLOR = "gray"
_MIN_TILE_PX_FOR_LABEL = 34
_DARK_TILE_LUMA = 150
_TICK_FONT_SIZE = 13
_AXIS_LABEL_FONT_SIZE = 14
_LEGEND_FONT_SIZE = 12


def _figure() -> Figure:
    fig = Figure(
        figsize=(PLOT_WIDTH_PX / 100, PLOT_HEIGHT_PX / 100),
        dpi=PLOT_DPI,
        facecolor="white",
    )
    FigureCanvasAgg(fig)
    return fig


def _figure_to_png(fig: Figure) -> bytes:
    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    return buf.getvalue()


def _party_color(party: str) -> str:
    return PARTY_COLORS.get(party, PARTY_COLOR_OTHER)


def _readable_text_color(hex_color: str) -> str:
    """Black on light tiles, white on dark ones (ITU-R BT.601 luma)."""
    raw = hex_color.lstrip("#")
    r, g, b = (int(raw[i : i + 2], 16) for i in (0, 2, 4))
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    return "#111111" if luma > _DARK_TILE_LUMA else "#ffffff"


# ---------------------------------------------------------------------------
# Squarified treemap layout
#
# Matplotlib has no treemap primitive, so lay the tiles out with the standard
# squarify algorithm (Bruls et al., 2000): fill the shorter side with a row of
# tiles for as long as doing so improves the worst aspect ratio, then recurse
# into whatever rectangle is left over.
# ---------------------------------------------------------------------------


def _layout_row(sizes: list[float], x: float, y: float, dy: float) -> list[dict]:
    width = sum(sizes) / dy
    rects = []
    for size in sizes:
        rects.append({"x": x, "y": y, "dx": width, "dy": size / width})
        y += size / width
    return rects


def _layout_col(sizes: list[float], x: float, y: float, dx: float) -> list[dict]:
    height = sum(sizes) / dx
    rects = []
    for size in sizes:
        rects.append({"x": x, "y": y, "dx": size / height, "dy": height})
        x += size / height
    return rects


def _layout(sizes: list[float], x: float, y: float, dx: float, dy: float) -> list[dict]:
    if dx >= dy:
        return _layout_row(sizes, x, y, dy)
    return _layout_col(sizes, x, y, dx)


def _leftover(
    sizes: list[float], x: float, y: float, dx: float, dy: float
) -> tuple[float, float, float, float]:
    if dx >= dy:
        width = sum(sizes) / dy
        return (x + width, y, dx - width, dy)
    height = sum(sizes) / dx
    return (x, y + height, dx, dy - height)


def _worst_ratio(sizes: list[float], x: float, y: float, dx: float, dy: float) -> float:
    return max(
        max(rect["dx"] / rect["dy"], rect["dy"] / rect["dx"])
        for rect in _layout(sizes, x, y, dx, dy)
    )


def _squarify(
    sizes: list[float], x: float, y: float, dx: float, dy: float
) -> list[dict]:
    if not sizes:
        return []
    if len(sizes) == 1 or dx <= 0 or dy <= 0:
        return _layout(sizes, x, y, dx, dy)

    split = 1
    while split < len(sizes) and _worst_ratio(
        sizes[:split], x, y, dx, dy
    ) >= _worst_ratio(sizes[: split + 1], x, y, dx, dy):
        split += 1

    current, remaining = sizes[:split], sizes[split:]
    return _layout(current, x, y, dx, dy) + _squarify(
        remaining, *_leftover(current, x, y, dx, dy)
    )


def _squarified_tiles(values: list[int], dx: float, dy: float) -> list[dict]:
    total = sum(values)
    if total <= 0:
        return []
    normalized = [v * dx * dy / total for v in values]
    return _squarify(normalized, 0.0, 0.0, dx, dy)


def render_party_treemap_png(
    records: list[DailyAccountPostCountRecord],
) -> bytes | None:
    """Treemap of total videos per party, or None when there is no data."""
    party_counts = sorted(
        (c for c in aggregate_party_counts(records) if c["count"] > 0),
        key=lambda c: c["count"],
        reverse=True,
    )
    if not party_counts:
        return None

    fig = _figure()
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_axis_off()
    ax.set_xlim(0, PLOT_WIDTH_PX)
    # Inverted so the squarify origin lands top-left, like the Plotly treemap.
    ax.set_ylim(PLOT_HEIGHT_PX, 0)

    tiles = _squarified_tiles(
        [c["count"] for c in party_counts], PLOT_WIDTH_PX, PLOT_HEIGHT_PX
    )
    pad = 3
    for tile, entry in zip(tiles, party_counts, strict=False):
        color = _party_color(entry["party"])
        ax.add_patch(
            FancyBboxPatch(
                (tile["x"] + pad, tile["y"] + pad),
                max(tile["dx"] - pad * 2, 1),
                max(tile["dy"] - pad * 2, 1),
                boxstyle="round,pad=0,rounding_size=6",
                facecolor=color,
                edgecolor="white",
                linewidth=1.5,
            )
        )
        if min(tile["dx"], tile["dy"]) < _MIN_TILE_PX_FOR_LABEL:
            continue
        ax.text(
            tile["x"] + tile["dx"] / 2,
            tile["y"] + tile["dy"] / 2,
            f"{entry['party']}\n{entry['count']}",
            ha="center",
            va="center",
            color=_readable_text_color(color),
            fontsize=min(18, max(8, min(tile["dx"], tile["dy"]) / 6)),
        )

    return _figure_to_png(fig)


def render_temporal_stacked_area_png(
    records: list[DailyAccountPostCountRecord],
) -> bytes | None:
    """Stacked daily videos per party, or None when there is no data."""
    daily_counts = aggregate_daily_party_counts(records)
    if not daily_counts:
        return None

    per_party: dict[str, dict[str, int]] = {}
    for record in daily_counts:
        per_party.setdefault(record["party"], {})[record["date"]] = record["count"]

    start = date.fromisoformat(min(r["date"] for r in daily_counts))
    end = date.fromisoformat(max(r["date"] for r in daily_counts))
    all_dates = [
        date.fromordinal(o).isoformat()
        for o in range(start.toordinal(), end.toordinal() + 1)
    ]

    # Plotly stacks traces in reversed party order (first trace at the bottom);
    # mirror that so the exported image matches the site.
    stacked_parties = [p for p in reversed(PARTIES_ORDER) if p in per_party]
    if not stacked_parties:
        return None

    series = [
        [per_party[party].get(day, 0) for day in all_dates] for party in stacked_parties
    ]

    fig = _figure()
    ax = fig.add_subplot(111)
    ax.stackplot(
        range(len(all_dates)),
        *series,
        labels=stacked_parties,
        colors=[_party_color(p) for p in stacked_parties],
        alpha=_AREA_ALPHA,
        edgecolor="none",
    )

    tick_dates = temporal_plot_xaxis_tickvals(all_dates)
    tick_positions = [all_dates.index(d) for d in tick_dates]
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(
        [date.fromisoformat(d).strftime("%d.%m") for d in tick_dates],
        rotation=45,
        ha="right",
    )
    ax.tick_params(labelsize=_TICK_FONT_SIZE)
    ax.set_xlim(0, max(len(all_dates) - 1, 1))
    ax.set_ylim(bottom=0)
    ax.set_xlabel("Datum", fontsize=_AXIS_LABEL_FONT_SIZE)
    ax.grid(visible=True, color=_GRID_COLOR, linewidth=0.5, alpha=0.5)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)

    handles, labels = ax.get_legend_handles_labels()
    ax.legend(
        handles[::-1],
        labels[::-1],
        loc="lower center",
        bbox_to_anchor=(0.5, 1.01),
        ncol=min(len(stacked_parties), 5),
        frameon=False,
        fontsize=_LEGEND_FONT_SIZE,
    )
    fig.tight_layout()
    return _figure_to_png(fig)


def render_png_for_slug(
    slug: str, records: list[DailyAccountPostCountRecord]
) -> bytes | None:
    renderers: dict[str, Any] = {
        "videos-gesamt": render_party_treemap_png,
        "videos-ueber-die-zeit": render_temporal_stacked_area_png,
    }
    if slug not in renderers:
        unknown = f"Unknown public plot slug: {slug}"
        raise ValueError(unknown)
    return renderers[slug](records)
