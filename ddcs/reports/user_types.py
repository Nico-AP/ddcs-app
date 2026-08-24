"""Fun TikTok usage typologies for the behaviour-profile intro / merch."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, TypedDict

if TYPE_CHECKING:
    from ddcs.reports.types import BehaviourComparisonRecord


_SESSION_LENGTH_NORM_SEC = 300.0
_MEDIAN_PERCENTILE = 50.0
_TEASER = "Swipe zur Seite, um dein Nutzungsprofil im Detail zu sehen →"

Direction = Literal["above", "below"]

# Single-metric types: (type_id, metric, direction vs reference distribution).
# Faultier is scored separately (long sessions + low skip rate).
_TYPE_RULES: tuple[tuple[str, str, Direction], ...] = (
    ("kolibri", "frac_instant_skip", "above"),
    ("luchs", "frac_political_engagement", "above"),
    ("eule", "night_activity_frac", "above"),
    ("waschbaer", "weekend_activity_frac", "above"),
    ("papagei", "rate_like", "above"),
)


class UserTypeRecord(TypedDict):
    id: str
    animal: str
    trait_label: str
    headline: str
    attention: str
    intro_followup: str
    teaser: str
    image_static: str


USER_TYPES: dict[str, UserTypeRecord] = {
    "kolibri": {
        "id": "kolibri",
        "animal": "Kolibri",
        "trait_label": "Skip-Spezialist",
        "headline": "Du bist der Kolibri",
        "attention": (
            "Bei politischen Videos lohnt sich manchmal der zweite Blick, "
            "bevor du weiter wischst."
        ),
        "intro_followup": (
            "Du fliegst von Clip zu Clip. Was dich reizt, erkennst du in Sekunden."
        ),
        "teaser": _TEASER,
        "image_static": "reports/img/types/kolibri.svg",
    },
    "faultier": {
        "id": "faultier",
        "animal": "Faultier",
        "trait_label": "chilliger Watcher",
        "headline": "Du bist das Faultier",
        "attention": (
            "Pass auf, dass du dich nicht zu sehr treiben lässt. "
            "Entscheide dich öfters dazu, die App zu schließen."
        ),
        "intro_followup": (
            "Du verbringst mehr Zeit am Stück auf TikTok und schaust dir die "
            "Videos länger an als die meisten."
        ),
        "teaser": _TEASER,
        "image_static": "reports/img/types/faultier.svg",
    },
    "eule": {
        "id": "eule",
        "animal": "Eule",
        "trait_label": "Nachteule",
        "headline": "Du bist die Eule",
        "attention": (
            "Nachts triffst du Entscheidungen lockerer, auch beim Liken "
            "und Teilen politischer Inhalte."
        ),
        "intro_followup": (
            "Deine Prime Time ist spät - ein großer Teil deiner TikToks läuft nachts."
        ),
        "teaser": _TEASER,
        "image_static": "reports/img/types/eule.svg",
    },
    "waschbaer": {
        "id": "waschbaer",
        "animal": "Waschbär",
        "trait_label": "Wochenend-Gucker",
        "headline": "Du bist der Waschbär",
        "attention": (
            "In langen Wochenend-Sessions ähneln sich die Inhalte schnell. "
            "Bewusst mal ausschalten und das Wochenende richtig genießen."
        ),
        "intro_followup": (
            "Unter der Woche ruhig, am Wochenende drehst du auf. "
            "Dein Feed ballt sich auf Samstag und Sonntag."
        ),
        "teaser": _TEASER,
        "image_static": "reports/img/types/waschbaer.svg",
    },
    "papagei": {
        "id": "papagei",
        "animal": "Papagei",
        "trait_label": "Fan",
        "headline": "Du bist der Papagei",
        "attention": (
            "Jeder Like formt deinen Feed. Achte darauf, auch mal auf Neues "
            "zu reagieren, um das immer Gleiche zu durchbrechen."
        ),
        "intro_followup": (
            "Du gibst gerne Likes. Das heißt, du zeigst deinem Feed genau, "
            "was du magst."
        ),
        "teaser": _TEASER,
        "image_static": "reports/img/types/papagei.svg",
    },
    "luchs": {
        "id": "luchs",
        "animal": "Luchs",
        "trait_label": "Politik-Beobachter",
        "headline": "Du bist der Luchs",
        "attention": (
            "Achte darauf, aus welchen Quellen politische Clips kommen — "
            "auch ein scharfer Blick braucht Kontext."
        ),
        "intro_followup": (
            "Du interessierst dich dafür was in der Welt passiert - "
            "und hast besonders oft mit politischen Videos interagiert."
        ),
        "teaser": _TEASER,
        "image_static": "reports/img/types/luchs.svg",
    },
}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _metric_rows(
    comparisons: list[BehaviourComparisonRecord],
) -> dict[str, BehaviourComparisonRecord]:
    return {row["metric"]: row for row in comparisons}


def _percentile_extremity(percentile: float, direction: Direction) -> float | None:
    """How far the percentile sits past the median in ``direction`` (0..50)."""
    if direction == "above":
        if percentile <= _MEDIAN_PERCENTILE:
            return None
        return percentile - _MEDIAN_PERCENTILE
    if percentile >= _MEDIAN_PERCENTILE:
        return None
    return _MEDIAN_PERCENTILE - percentile


def _faultier_percentile_score(
    rows: dict[str, BehaviourComparisonRecord],
) -> float | None:
    """Faultier needs long sessions and below-average skip rate."""
    session_row = rows.get("avg_session_length_sec")
    skip_row = rows.get("frac_instant_skip")
    if session_row is None or skip_row is None:
        return None
    session_score = _percentile_extremity(float(session_row["percentile"]), "above")
    skip_score = _percentile_extremity(float(skip_row["percentile"]), "below")
    if session_score is None or skip_score is None:
        return None
    # Strength is limited by the weaker of the two traits.
    return min(session_score, skip_score)


def _strongest_percentile_type(
    rows: dict[str, BehaviourComparisonRecord],
) -> str | None:
    """Pick the type with the largest one-sided distance from the median percentile."""
    best_id: str | None = None
    best_score = -1.0
    for type_id, metric, direction in _TYPE_RULES:
        row = rows.get(metric)
        if row is None:
            continue
        score = _percentile_extremity(float(row["percentile"]), direction)
        if score is None:
            continue
        if score > best_score:
            best_score = score
            best_id = type_id

    faultier_score = _faultier_percentile_score(rows)
    if faultier_score is not None and faultier_score > best_score:
        return "faultier"
    return best_id


def _row_value(
    rows: dict[str, BehaviourComparisonRecord],
    metric: str,
    default: float = 0.0,
) -> float:
    row = rows.get(metric)
    if row is None:
        return default
    return float(row["value"])


def _absolute_specialty_scores(
    rows: dict[str, BehaviourComparisonRecord],
) -> dict[str, float]:
    """Fallback scores from absolute metric levels (no reference comparison)."""
    skip = _clamp01(_row_value(rows, "frac_instant_skip"))
    session = _clamp01(
        _row_value(rows, "avg_session_length_sec") / _SESSION_LENGTH_NORM_SEC
    )
    night = _clamp01(_row_value(rows, "night_activity_frac"))
    weekend = _clamp01(_row_value(rows, "weekend_activity_frac"))
    like_rate = _clamp01(_row_value(rows, "rate_like"))
    political = _clamp01(_row_value(rows, "frac_political_engagement"))

    return {
        "kolibri": skip,
        "faultier": (session + (1.0 - skip)) / 2.0,
        "luchs": political,
        "eule": night,
        "waschbaer": weekend,
        "papagei": like_rate,
    }


def assign_user_type(
    comparisons: list[BehaviourComparisonRecord],
) -> UserTypeRecord | None:
    """Assign a typology from comparison rows (filter-stable if unfiltered).

    1. Prefer the type whose defining metric(s) are farthest past the median
       percentile in the expected direction (shared 0-50 scale). Faultier
       requires both long sessions and below-average skip rate.
    2. If none qualify, fall back to the strongest absolute within-user signal.
    """
    if not comparisons:
        return None

    rows = _metric_rows(comparisons)
    percentile_id = _strongest_percentile_type(rows)
    if percentile_id is not None:
        return USER_TYPES[percentile_id]

    scores = _absolute_specialty_scores(rows)
    best_id = max(scores, key=scores.get)
    return USER_TYPES[best_id]
