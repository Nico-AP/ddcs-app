"""Fun TikTok usage typologies for the behaviour-profile intro slide / merch."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, TypedDict

if TYPE_CHECKING:
    from ddcs.reports.types import BehaviourComparisonRecord

_SESSION_LENGTH_NORM_SEC = 300.0
_SPECIALTY_THRESHOLD = 0.45
_TEASER = "Swipe zur Seite, um dein Nutzungsprofil im Detail zu sehen →"

Direction = Literal["above", "below"]

# (type_id, metric, direction vs reference mean)
_TYPE_RULES: tuple[tuple[str, str, Direction], ...] = (
    ("kolibri", "frac_instant_skip", "above"),
    ("faultier", "avg_session_length_sec", "above"),
    ("luchs", "frac_instant_skip", "below"),
    ("eule", "night_activity_frac", "above"),
    ("waschbaer", "weekend_activity_frac", "above"),
    ("papagei", "rate_like", "above"),
)


class UserTypeRecord(TypedDict):
    id: str
    animal: str
    trait_label: str
    headline: str
    description: str
    attention: str
    teaser: str
    image_static: str


USER_TYPES: dict[str, UserTypeRecord] = {
    "kolibri": {
        "id": "kolibri",
        "animal": "Kolibri",
        "trait_label": "Der Skip-Spezialist",
        "headline": "Du bist der Kolibri",
        "description": (
            "Du fliegst von Clip zu Clip. Was dich reizt, erkennst du in Sekunden."
        ),
        "attention": (
            "Bei politischen Videos lohnt sich manchmal der zweite Blick, "
            "bevor du weiter wischst."
        ),
        "teaser": _TEASER,
        "image_static": "reports/img/types/kolibri.svg",
    },
    "faultier": {
        "id": "faultier",
        "animal": "Faultier",
        "trait_label": "Der chillige Watcher",
        "headline": "Du bist das Faultier",
        "description": ("Du bist auf TikTok länger am Stück als die Meisten."),
        "attention": (
            "Pass auf, dass du dich nicht zu sehr treiben lässt. "
            "Entscheide dich öfters dazu, die App zu schließen."
        ),
        "teaser": _TEASER,
        "image_static": "reports/img/types/faultier.svg",
    },
    "eule": {
        "id": "eule",
        "animal": "Eule",
        "trait_label": "Die Nachteule",
        "headline": "Du bist die Eule",
        "description": (
            "Deine Prime Time ist spät - ein großer Teil deiner TikToks "
            "läuft nach Mitternacht."
        ),
        "attention": (
            "Nachts triffst du Entscheidungen lockerer, auch beim Liken "
            "und Teilen politischer Inhalte."
        ),
        "teaser": _TEASER,
        "image_static": "reports/img/types/eule.svg",
    },
    "waschbaer": {
        "id": "waschbaer",
        "animal": "Waschbär",
        "trait_label": "Der Wochenend-Gucker",
        "headline": "Du bist der Waschbär",
        "description": (
            "Unter der Woche ruhig, am Wochenende drehst du auf. "
            "Dein Feed ballt sich auf Samstag und Sonntag."
        ),
        "attention": (
            "In langen Wochenend-Sessions ähneln sich die Inhalte schnell. "
            "Bewusst mal ausschalten und das Wochenende richtig genießen."
        ),
        "teaser": _TEASER,
        "image_static": "reports/img/types/waschbaer.svg",
    },
    "papagei": {
        "id": "papagei",
        "animal": "Papagei",
        "trait_label": "Der Fan",
        "headline": "Du bist der Papagei",
        "description": (
            "Du gibst gerne Likes und interagierst viel. Das heißt, du zeigst "
            "deinem Feed genau, was du magst."
        ),
        "attention": (
            "Jeder Like formt deinen Feed. Achte darauf, auch mal auf Neues "
            "zu reagieren, um das immer Gleiche zu durchbrechen."
        ),
        "teaser": _TEASER,
        "image_static": "reports/img/types/papagei.svg",
    },
    "luchs": {
        "id": "luchs",
        "animal": "Luchs",
        "trait_label": "Der Beobachter",
        "headline": "Du bist der Luchs",
        "description": "Du schaust Videos länger als die Meisten.",
        "attention": "Skip auch mal was dir nicht gefällt.",
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


def _relative_deviation(
    value: float,
    average: float,
    direction: Direction,
) -> float | None:
    """One-sided relative deviation from the mean, or None if not qualifying."""
    if direction == "above":
        if value <= average:
            return None
        span = value - average
    else:
        if value >= average:
            return None
        span = average - value

    # Normalize by |avg| so seconds and fractions are comparable; avoid /0.
    scale = abs(average) if average != 0.0 else 1.0
    return span / scale


def _strongest_relative_type(
    rows: dict[str, BehaviourComparisonRecord],
) -> str | None:
    """Pick the type with the largest one-sided deviation from the mean."""
    best_id: str | None = None
    best_dev = -1.0
    for type_id, metric, direction in _TYPE_RULES:
        row = rows.get(metric)
        if row is None:
            continue
        deviation = _relative_deviation(
            float(row["value"]),
            float(row["reference_mean"]),
            direction,
        )
        if deviation is None:
            continue
        if deviation > best_dev:
            best_dev = deviation
            best_id = type_id
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

    return {
        "kolibri": skip,
        "faultier": session,
        "luchs": 1.0 - skip,
        "eule": night,
        "waschbaer": weekend,
        "papagei": like_rate,
    }


def assign_user_type(
    comparisons: list[BehaviourComparisonRecord],
) -> UserTypeRecord | None:
    """Assign a typology from comparison rows (filter-stable if unfiltered means).

    1. Prefer the type whose defining metric most strongly beats the reference
       mean in the expected direction (above or below).
    2. If none qualify, fall back to absolute specialty scores; if the best
       absolute score is still weak, assign Luchs.
    """
    if not comparisons:
        return None

    rows = _metric_rows(comparisons)
    relative_id = _strongest_relative_type(rows)
    if relative_id is not None:
        return USER_TYPES[relative_id]

    scores = _absolute_specialty_scores(rows)
    best_id = max(scores, key=scores.get)
    if scores[best_id] < _SPECIALTY_THRESHOLD:
        best_id = "luchs"
    return USER_TYPES[best_id]
