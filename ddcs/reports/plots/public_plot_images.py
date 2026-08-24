"""Persist homepage public plots as PNG files for embedding."""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings
from PIL import Image, ImageDraw, ImageFont
from plotly.graph_objects import Figure

from ddcs.reports.factories import get_synthetic_post_data
from ddcs.reports.metrics.account_metrics import get_post_data
from ddcs.reports.plots.public_plots import (
    build_party_distribution_figure,
    build_temporal_party_distribution_figure,
)
from ddcs.website.dashboard_export import nationwide_export_meta

if TYPE_CHECKING:
    from ddcs.reports.types import DailyAccountPostCountRecord

logger = logging.getLogger(__name__)

PUBLIC_PLOT_IMAGE_DIR = "public-plots"
PUBLIC_PLOT_IMAGE_SLUGS = ("videos-gesamt", "videos-ueber-die-zeit")

_PLOT_WIDTH = 1200
_PLOT_HEIGHT = 560
_PAD = 36
_TITLE_SIZE = 28
_CAPTION_SIZE = 16
_LINE_GAP = 6
_SECTION_GAP = 20


def public_plot_image_relpath(slug: str) -> str:
    return f"{PUBLIC_PLOT_IMAGE_DIR}/{slug}.png"


def public_plot_image_path(slug: str) -> Path:
    return Path(settings.MEDIA_ROOT) / public_plot_image_relpath(slug)


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    names = (
        ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf")
        if bold
        else ("DejaVuSans.ttf", "DejaVuSans.ttf")
    )
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            continue
        current = words[0]
        for word in words[1:]:
            trial = f"{current} {word}"
            if draw.textlength(trial, font=font) <= max_width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _text_block_height(lines: list[str], line_height: int) -> int:
    if not lines:
        return 0
    return len(lines) * line_height + max(len(lines) - 1, 0) * _LINE_GAP


def compose_labeled_png(plot_png: bytes, title: str, caption: str) -> bytes:
    plot = Image.open(BytesIO(plot_png)).convert("RGB")
    title_font = _font(_TITLE_SIZE, bold=True)
    caption_font = _font(_CAPTION_SIZE)
    text_width = plot.width

    scratch = ImageDraw.Draw(plot)
    title_lines = _wrap_text(scratch, title, title_font, text_width) if title else []
    caption_lines = (
        _wrap_text(scratch, caption, caption_font, text_width) if caption else []
    )
    title_lh = _TITLE_SIZE + 6
    caption_lh = _CAPTION_SIZE + 4
    title_h = _text_block_height(title_lines, title_lh)
    caption_h = _text_block_height(caption_lines, caption_lh)

    canvas_h = (
        _PAD
        + title_h
        + (_SECTION_GAP if title_h else 0)
        + plot.height
        + (_SECTION_GAP if caption_h else 0)
        + caption_h
        + _PAD
    )
    canvas = Image.new("RGB", (plot.width + _PAD * 2, canvas_h), "white")
    draw = ImageDraw.Draw(canvas)
    y = _PAD
    for line in title_lines:
        draw.text((_PAD, y), line, fill="#111111", font=title_font)
        y += title_lh + _LINE_GAP
    if title_lines:
        y += _SECTION_GAP - _LINE_GAP
    canvas.paste(plot, (_PAD, y))
    y += plot.height
    if caption_lines:
        y += _SECTION_GAP
        for line in caption_lines:
            draw.text((_PAD, y), line, fill="#444444", font=caption_font)
            y += caption_lh + _LINE_GAP

    out = BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


def _figure_to_png(fig: Figure) -> bytes:
    export_fig = Figure(fig)
    export_fig.update_layout(paper_bgcolor="white", plot_bgcolor="white")
    try:
        return export_fig.to_image(
            format="png",
            width=_PLOT_WIDTH,
            height=_PLOT_HEIGHT,
            scale=2,
        )
    except ValueError as exc:
        msg = (
            "PNG export requires the kaleido package. "
            "Install it with: pip install kaleido"
        )
        raise RuntimeError(msg) from exc


def _homepage_records() -> list[DailyAccountPostCountRecord]:
    return get_synthetic_post_data() if settings.DEBUG else get_post_data()


def meta_for_slug(slug: str) -> dict[str, str]:
    meta = nationwide_export_meta()
    key = "videos_gesamt" if slug == "videos-gesamt" else "videos_zeit"
    return meta[key]


def figure_for_slug(
    slug: str,
    records: list[DailyAccountPostCountRecord] | None = None,
) -> Figure | None:
    data = records if records is not None else _homepage_records()
    if slug == "videos-gesamt":
        return build_party_distribution_figure(data)
    if slug == "videos-ueber-die-zeit":
        return build_temporal_party_distribution_figure(data)
    unknown = f"Unknown public plot slug: {slug}"
    raise ValueError(unknown)


def write_public_plot_png(
    slug: str,
    *,
    records: list[DailyAccountPostCountRecord] | None = None,
) -> Path:
    if slug not in PUBLIC_PLOT_IMAGE_SLUGS:
        unknown = f"Unknown public plot slug: {slug}"
        raise ValueError(unknown)
    fig = figure_for_slug(slug, records)
    if fig is None:
        missing = f"No data to render public plot '{slug}'"
        raise RuntimeError(missing)
    labels = meta_for_slug(slug)
    png = compose_labeled_png(
        _figure_to_png(fig),
        labels["title"],
        labels["caption"],
    )
    path = public_plot_image_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return path


def refresh_public_plot_images() -> list[Path]:
    records = _homepage_records()
    written: list[Path] = []
    for slug in PUBLIC_PLOT_IMAGE_SLUGS:
        try:
            written.append(write_public_plot_png(slug, records=records))
        except (OSError, RuntimeError, ValueError):
            logger.exception("Failed to write public plot PNG for %s", slug)
    return written
