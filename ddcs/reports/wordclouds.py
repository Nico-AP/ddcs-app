import re
import unicodedata
from collections import Counter
from collections.abc import Callable
from typing import Any

from wordcloud import STOPWORDS, WordCloud

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
# Distinct from brand teal (#0cc4b6) used elsewhere in the report.
RGB_VIOLET = (118, 72, 180)

GERMAN_STOPWORDS = frozenset(
    [
        "aber",
        "alle",
        "allem",
        "allen",
        "aller",
        "alles",
        "als",
        "also",
        "am",
        "an",
        "ander",
        "andere",
        "anderem",
        "anderen",
        "anderer",
        "anderes",
        "anderm",
        "andern",
        "anderr",
        "anders",
        "auch",
        "auf",
        "aus",
        "bei",
        "bin",
        "bis",
        "bist",
        "da",
        "damit",
        "dann",
        "das",
        "dasselbe",
        "dazu",
        "daß",
        "dein",
        "deine",
        "deinem",
        "deinen",
        "deiner",
        "deines",
        "dem",
        "demselben",
        "den",
        "denn",
        "denselben",
        "der",
        "derer",
        "derselbe",
        "derselben",
        "des",
        "desselben",
        "dessen",
        "dich",
        "die",
        "dies",
        "diese",
        "dieselbe",
        "dieselben",
        "diesem",
        "diesen",
        "dieser",
        "dieses",
        "dir",
        "doch",
        "dort",
        "du",
        "dürft",
        "dürfen",
        "durfte",
        "durften",
        "ein",
        "eine",
        "einem",
        "einen",
        "einer",
        "eines",
        "einig",
        "einige",
        "einigem",
        "einigen",
        "einiger",
        "einiges",
        "einmal",
        "er",
        "es",
        "etwas",
        "euch",
        "euer",
        "eure",
        "eurem",
        "euren",
        "eurer",
        "eures",
        "für",
        "gegen",
        "gewesen",
        "hab",
        "habe",
        "haben",
        "habt",
        "hast",
        "hat",
        "hatte",
        "hatten",
        "hattest",
        "hattet",
        "hier",
        "hin",
        "hinter",
        "ich",
        "ihm",
        "ihn",
        "ihnen",
        "ihr",
        "ihre",
        "ihrem",
        "ihren",
        "ihrer",
        "ihres",
        "im",
        "in",
        "indem",
        "ins",
        "ist",
        "jede",
        "jedem",
        "jeden",
        "jeder",
        "jedes",
        "jene",
        "jenem",
        "jenen",
        "jener",
        "jenes",
        "jetzt",
        "kann",
        "kannst",
        "kein",
        "keine",
        "keinem",
        "keinen",
        "keiner",
        "keines",
        "können",
        "könnt",
        "konnte",
        "konnten",
        "mag",
        "magst",
        "mich",
        "mir",
        "mit",
        "muss",
        "musst",
        "müssen",
        "müsst",
        "nach",
        "nicht",
        "nichts",
        "noch",
        "nun",
        "nur",
        "ob",
        "oder",
        "ohne",
        "schon",
        "seid",
        "sein",
        "seine",
        "seinem",
        "seinen",
        "seiner",
        "seines",
        "selbst",
        "sich",
        "sie",
        "sind",
        "so",
        "solche",
        "solchem",
        "solchen",
        "solcher",
        "solches",
        "soll",
        "sollen",
        "sollst",
        "sollt",
        "sollte",
        "sollten",
        "sondern",
        "sonst",
        "um",
        "und",
        "uns",
        "unse",
        "unsem",
        "unsen",
        "unser",
        "unsere",
        "unses",
        "unter",
        "vom",
        "von",
        "vor",
        "während",
        "war",
        "waren",
        "warst",
        "warum",
        "was",
        "weg",
        "weil",
        "weiter",
        "welche",
        "welchem",
        "welchen",
        "welcher",
        "welches",
        "wenn",
        "werde",
        "werden",
        "werdet",
        "wie",
        "wieder",
        "will",
        "willst",
        "wir",
        "wird",
        "wirst",
        "wo",
        "wollen",
        "wollt",
        "wollte",
        "wollten",
        "würde",
        "würden",
        "zu",
        "zum",
        "zur",
        "zwar",
        "zwischen",
    ]
)

REPORT_STOPWORDS = (
    STOPWORDS | GERMAN_STOPWORDS | {w.lower() for w in HASHTAGS_TO_EXCLUDE}
)

_TOKEN_PATTERN = re.compile(WORDCLOUD_CONFIG["regexp"], re.UNICODE)
_MIN_TOKEN_LENGTH = 2


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


def _build_description_frequencies(descriptions: list[str]) -> Counter:
    """Tokenize video descriptions and count word frequencies."""
    counter: Counter = Counter()
    for text in descriptions:
        if not text:
            continue
        for word in _TOKEN_PATTERN.findall(text.lower()):
            cleaned = _remove_emojis(word)
            if len(cleaned) < _MIN_TOKEN_LENGTH or cleaned in REPORT_STOPWORDS:
                continue
            counter[cleaned] += 1
    return counter


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


def _responsive_wordcloud_svg(svg: str) -> str:
    """Add viewBox so the fixed-size SVG scales to its container width."""
    width = WORDCLOUD_CONFIG["width"]
    height = WORDCLOUD_CONFIG["height"]
    if "viewBox=" in svg:
        return svg
    return svg.replace(
        "<svg ",
        (f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet" '),
        1,
    )


def _create_wordcloud(frequencies: Counter, color_rgb: tuple[int, int, int]) -> dict:
    """Generate a wordcloud SVG from frequencies and a base RGB color."""
    if not frequencies:
        return {"html": None}

    cloud = WordCloud(
        **WORDCLOUD_CONFIG,
        stopwords=REPORT_STOPWORDS,
        color_func=_make_color_func(frequencies, *color_rgb),
    ).generate_from_frequencies(frequencies)

    svg = _responsive_wordcloud_svg(cloud.to_svg(embed_font=False))
    return {
        "html": f'<div class="wordcloud-container">{svg}</div>',
    }


def get_wordcloud(descriptions: list[str], *, is_party_account: bool) -> dict:
    """Build a description wordcloud for one of the two report sections.

    ``is_party_account=True`` colours the cloud orange (party-aligned videos);
    ``False`` colours it turquoise (non-party political videos).
    """
    color = RGB_ORANGE if is_party_account else RGB_VIOLET
    return _create_wordcloud(_build_description_frequencies(descriptions), color)
