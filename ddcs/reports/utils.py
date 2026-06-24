import csv
from functools import lru_cache
from pathlib import Path

from ddcs.reports.config import ACCOUNT_PARTY_MAPPING_CSV_PATH


@lru_cache(maxsize=1)
def load_account_party_mapping() -> dict[str, str]:
    """Load account-party map from reports/data/account_party_mapping.csv as dict.

    Cached for the lifetime of the process; call
    ``load_account_party_mapping.cache_clear()`` after editing the CSV in
    long-running processes (or in tests).

    Key = username, value = party.
    """
    with Path(ACCOUNT_PARTY_MAPPING_CSV_PATH).open("r", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file, delimiter=",")
        return {row["username"]: row["partei"] for row in reader}
