from datetime import UTC, datetime
from pathlib import Path

_DATA_DIR = Path(__file__).parent / "data"
ACCOUNT_PARTY_MAPPING_CSV_PATH = _DATA_DIR / "account_party_mapping.csv"
BEHAVIOUR_METRICS_CSV_PATH = _DATA_DIR / "behaviour_metrics_per_participant.csv"

PLOTLY_JS_STATIC_PATH = "reports/js/plotly-3.6.0.min.js"
REPORT_FIRST_DATE_TO_INCLUDE = datetime(2026, 5, 1, tzinfo=UTC)
NO_PARTY_KEY = "Keine Partei"

PARTIES_ORDER = [
    "SPD",
    "CDU/CSU",
    "Grüne",
    "B90/Grüne",
    "FDP",
    "AfD",
    "Linke",
    "BSW",
    "Sonstige",
    "Keine Partei",
]

N_TOP_VIDEOS = 3

HASHTAGS_TO_EXCLUDE = {
    "capcut",
    "foryou",
    "fürdich",
    "fy",
    "fyp",
    "trending",
    "viral",
}
