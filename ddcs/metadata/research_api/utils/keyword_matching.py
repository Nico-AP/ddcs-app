import re
from functools import cache

from ddcs.metadata.models import Keyword


@cache
def _boundary_pattern(keyword: str) -> re.Pattern:
    """Match `keyword` as a whole unit, regardless of what characters
    the keyword itself starts or ends with."""
    escaped = re.escape(keyword)
    return re.compile(rf"(?<![^\W_]){escaped}(?![^\W_])", re.IGNORECASE)


def find_matching_keywords(
    keywords: list[Keyword],
    description: str,
    hashtag_names: list[str],
) -> list[Keyword]:
    """Return the subset of `keywords` present in the description or hashtags.

    Hashtag matching is exact (case-insensitive). Description matching
    requires the keyword to appear as a standalone unit — not glued to
    surrounding letters/digits — so "cat" won't match inside "category",
    but keywords starting/ending in punctuation (e.g. "#trend", "co.")
    are still matched correctly.
    """
    hashtag_names_lower = {h.lower() for h in hashtag_names}
    description = description or ""

    return [
        kw
        for kw in keywords
        if kw.name.lower() in hashtag_names_lower
        or _boundary_pattern(kw.name).search(description)
    ]
