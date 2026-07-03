from datetime import UTC, date, datetime
from pathlib import Path

_DATA_DIR = Path(__file__).parent / "data"
ACCOUNT_PARTY_MAPPING_CSV_PATH = _DATA_DIR / "account_party_mapping.csv"
BEHAVIOUR_METRICS_CSV_PATH = _DATA_DIR / "behaviour_metrics_per_participant.csv"

PLOTLY_JS_STATIC_PATH = "reports/js/plotly-3.6.0.min.js"
REPORT_FIRST_DATE_TO_INCLUDE = datetime(2026, 5, 1, tzinfo=UTC)
NO_PARTY_KEY = "Keine Partei"

# Public (cross-account) report: window of dates covered by `get_post_data`.
# The end lag accounts for the Research API sync/backfill delay, so the most
# recent days (which may still be incompletely synced) are excluded.
PUBLIC_POST_DATA_START_DATE = date(2026, 6, 1)
PUBLIC_POST_DATA_END_LAG_DAYS = 4

PARTIES_ORDER = [
    "SPD",
    "CDU/CSU",
    "B90/GRÜNE",
    "FDP",
    "AfD",
    "Linke",
    "BSW",
    "Sonstige",
    "Keine Partei",
]

N_TOP_VIDEOS = 5

HASHTAGS_TO_EXCLUDE = {
    "capcut",
    "foryou",
    "fürdich",
    "fy",
    "fyp",
    "trending",
    "viral",
}
