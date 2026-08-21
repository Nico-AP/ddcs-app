"""Load monitored keyword/account lists for the public methods page."""

from __future__ import annotations

import csv
from functools import lru_cache
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any

from openpyxl import Workbook

from ddcs.reports.config import ACCOUNT_PARTY_MAPPING_CSV_PATH
from ddcs.reports.metrics.account_metrics import _recode_party

_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "metadata" / "fixtures"
MONITORED_USERS_CSV_PATH = _FIXTURES_DIR / "monitored_users.csv"
MONITORED_KEYWORDS_CSV_PATH = _FIXTURES_DIR / "monitored_keywords.csv"

_BUNDESLAND_LABELS = {
    "BE": "Berlin",
    "MV": "Mecklenburg-Vorpommern",
    "SA": "Sachsen-Anhalt",
    "Andere": "Andere",
}


def bundesland_label(code: str) -> str:
    if not code:
        return ""
    return _BUNDESLAND_LABELS.get(code, code)


def _read_name_list(path: Path) -> list[str]:
    """Parse name[,priority] lines; blank/# lines ignored; first occurrence wins."""
    text = path.read_text(encoding="utf-8")
    seen: set[str] = set()
    names: list[str] = []
    for row in csv.reader(StringIO(text)):
        if not row:
            continue
        raw_name = row[0].strip()
        if not raw_name or raw_name.startswith("#") or raw_name in seen:
            continue
        seen.add(raw_name)
        names.append(raw_name)
    return names


@lru_cache(maxsize=1)
def load_monitored_keywords() -> list[str]:
    return _read_name_list(MONITORED_KEYWORDS_CSV_PATH)


@lru_cache(maxsize=1)
def load_account_affiliations() -> dict[str, dict[str, str]]:
    """username -> {party, bundesland, bundesland_label}.

    Party labels are normalized via ``_recode_party`` (CDU/CSU merge;
    minor parties → Sonstige).
    """
    with Path(ACCOUNT_PARTY_MAPPING_CSV_PATH).open("r", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file, delimiter=",")
        result: dict[str, dict[str, str]] = {}
        for row in reader:
            username = row["username"].strip()
            bundesland = row.get("bundesland", "").strip()
            raw_party = row.get("partei", "").strip()
            result[username] = {
                "party": _recode_party(raw_party) if raw_party else "",
                "bundesland": bundesland,
                "bundesland_label": bundesland_label(bundesland),
            }
        return result


@lru_cache(maxsize=1)
def load_monitored_accounts() -> list[dict[str, str]]:
    """Monitored usernames enriched with party and federal state."""
    affiliations = load_account_affiliations()
    accounts: list[dict[str, str]] = []
    for username in _read_name_list(MONITORED_USERS_CSV_PATH):
        info = affiliations.get(username, {})
        accounts.append(
            {
                "username": username,
                "party": info.get("party", ""),
                "bundesland": info.get("bundesland", ""),
                "bundesland_label": info.get("bundesland_label", ""),
            }
        )
    return accounts


def get_methods_lists_payload() -> dict[str, Any]:
    return {
        "keywords": load_monitored_keywords(),
        "accounts": [
            {
                "username": a["username"],
                "party": a["party"],
                "bundesland": a["bundesland"],
            }
            for a in load_monitored_accounts()
        ],
    }


def build_methods_lists_xlsx() -> bytes:
    payload = get_methods_lists_payload()
    wb = Workbook()

    ws_kw = wb.active
    ws_kw.title = "keywords"
    ws_kw.append(["keyword"])
    for name in payload["keywords"]:
        ws_kw.append([name])

    ws_acc = wb.create_sheet("accounts")
    ws_acc.append(["username", "party", "bundesland"])
    for row in payload["accounts"]:
        ws_acc.append([row["username"], row["party"], row["bundesland"]])

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
