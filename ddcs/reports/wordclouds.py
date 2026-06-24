import unicodedata
from collections import Counter
from collections.abc import Callable
from typing import Any

from wordcloud import WordCloud

from ddcs.reports.config import HASHTAGS_TO_EXCLUDE

WORDCLOUD_CONFIG = {
    "width": 800,
    "height": 600,
    "background_color": None,
    "max_words": 100,
    "prefer_horizontal": 0.7,
    "min_font_size": 10,
    "max_font_size": 100,
    "include_numbers": True,
    "regexp": r"\w+[\w'-]*",
}

RGB_ORANGE = (255, 191, 0)
RGB_TURQUOISE = (0, 191, 150)


def _remove_emojis(tag: str) -> str:
    """Drop emoji and other symbols/punctuation,
    keep letters and numbers (incl. ä/ö/ü/ß).
    """
    return "".join(
        char
        for char in tag
        if unicodedata.category(char)[0] in ("L", "N")
        # L matches letters and N matches numbers
    ).lower()


def _build_hashtag_frequencies(hashtags: list[str]) -> Counter:
    """Build a frequency counter, filtering common tags and emoji-only tags."""
    all_hashtags = []
    for hashtag in hashtags:
        if hashtag.lower() in HASHTAGS_TO_EXCLUDE:
            continue
        cleaned = _remove_emojis(hashtag)
        if cleaned:
            all_hashtags.append(cleaned)
    return Counter(all_hashtags)


def _make_color_func(
    frequencies: Counter, r: int, g: int, b: int
) -> Callable[..., str]:
    """Create a wordcloud color function that scales color intensity
    by word frequency.
    """
    max_freq = max(frequencies.values())

    def color_func(
        word: str,
        font_size: int,
        position: tuple[int, int],
        orientation: int | None,
        random_state: Any | None = None,  # noqa: ANN401
        **kwargs,
    ) -> str:
        intensity = frequencies[word] / max_freq
        return f"rgb({int(r * intensity)}, {int(g * intensity)}, {int(b * intensity)})"

    return color_func


def _create_wordcloud(frequencies: Counter, color_rgb: tuple[int, int, int]) -> dict:
    """Generate a wordcloud SVG from frequencies and a base RGB color."""
    if not frequencies:
        return {"html": None}

    cloud = WordCloud(
        **WORDCLOUD_CONFIG,
        color_func=_make_color_func(frequencies, *color_rgb),
    ).generate_from_frequencies(frequencies)

    return {
        "html": (
            f'<div class="wordcloud-container">{cloud.to_svg(embed_font=False)}</div>'
        )
    }


def get_wordcloud(hashtags: list[str], *, is_party_account: bool) -> dict:
    """Build a hashtag wordcloud for one of the two report sections.

    ``is_party_account=True`` colours the cloud orange (party-aligned videos);
    ``False`` colours it turquoise (non-party political videos).
    """
    color = RGB_ORANGE if is_party_account else RGB_TURQUOISE
    return _create_wordcloud(_build_hashtag_frequencies(hashtags), color)
