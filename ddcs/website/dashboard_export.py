"""German titles and captions for public-dashboard PNG exports."""

from __future__ import annotations

from datetime import date
from typing import Any

from django.conf import settings
from django.utils.formats import date_format

from ddcs.reports.metrics.public_dashboard import get_monitored_video_stats

BUNDESLAND_LABELS = {
    "BE": "Berlin",
    "MV": "Mecklenburg-Vorpommern",
    "SA": "Sachsen-Anhalt",
}

BUNDESLAND_PARLIAMENT = {
    "BE": "das Abgeordnetenhaus von Berlin",
    "MV": "den Landtag Mecklenburg-Vorpommern",
    "SA": "den Landtag Sachsen-Anhalt",
}


def format_de_date(value: str | date | None) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        value = date.fromisoformat(value)
    return date_format(value, "j. F Y")


def _scope_text(bundesland: str) -> str:
    if bundesland:
        land = BUNDESLAND_LABELS.get(bundesland, bundesland)
        parliament = BUNDESLAND_PARLIAMENT.get(bundesland)
        if parliament:
            return (
                f"Erfasst werden Videos der {land} zugeordneten Partei-Accounts "
                f"(Landesverbände und Kandidierende für {parliament})."
            )
        return f"Erfasst werden Videos der {land} zugeordneten Partei-Accounts."
    return (
        "Erfasst werden Videos offizieller Partei-Accounts in ganz Deutschland: "
        "Bundes- und Landesverbände sowie Accounts von Kandidierenden für "
        "Bundestag und Landtage."
    )


def _period_line(stats: dict[str, Any]) -> str:
    start = format_de_date(stats.get("start_date"))
    end = format_de_date(stats.get("end_date"))
    n_accounts = stats.get("n_accounts")
    if start and end:
        line = f"Zeitraum: {start} bis {end}"
    else:
        line = "Zeitraum: ab 1. Juli 2026 bis vier Tage vor dem aktuellen Datum"
    if n_accounts:
        line += f" ({n_accounts} Accounts)"
    return line + "."


CREDIT_LINE = "Grafik: Dein Feed, Deine Wahl."
SOURCE_LINE = "Quelle: TikTok Research API."
TIERZEICHEN_SOURCE_LINE = "Quelle: Datenspende Dein Feed, Deine Wahl."


def _caption(lead: str, period_line: str, scope: str) -> str:
    return f"{lead}\n{period_line}\n{scope}\n{SOURCE_LINE}\n{CREDIT_LINE}"


def build_dashboard_export_meta(
    *,
    video_stats: dict[str, Any] | None,
    selected_bundesland: str = "",
) -> dict[str, dict[str, str]]:
    """Return title/caption dicts keyed for dashboard export buttons."""
    stats = video_stats or {}
    period = _period_line(stats)
    scope = _scope_text(selected_bundesland)

    def party_caption(lead: str) -> str:
        return _caption(lead, period, scope)

    return {
        "videos_gesamt": {
            "title": "Videos von Partei-Accounts nach Partei",
            "caption": party_caption(
                "Anzahl der auf TikTok veröffentlichten Videos, kumuliert nach Partei."
            ),
        },
        "videos_zeit": {
            "title": "Tägliche Videoanzahl von Partei-Accounts",
            "caption": party_caption(
                "Gestapelte Fläche der täglich veröffentlichten Videos nach Partei."
            ),
        },
        "views_gesamt": {
            "title": "Aufrufe von Videos der Partei-Accounts nach Partei",
            "caption": party_caption(
                "Summe der Aufrufe (Views) aller im Zeitraum von den "
                "Partei-Accounts veröffentlichten Videos."
            ),
        },
        "views_pro_video": {
            "title": "Durchschnittliche Aufrufe pro Video nach Partei",
            "caption": party_caption(
                "Mittlere Anzahl Aufrufe je im Zeitraum veröffentlichtem Video."
            ),
        },
        "likes_gesamt": {
            "title": "Likes auf Videos der Partei-Accounts nach Partei",
            "caption": party_caption(
                "Summe der Likes aller im Zeitraum von den Partei-Accounts "
                "veröffentlichten Videos."
            ),
        },
        "likes_pro_video": {
            "title": "Durchschnittliche Likes pro Video nach Partei",
            "caption": party_caption(
                "Mittlere Anzahl Likes je im Zeitraum veröffentlichtem Video."
            ),
        },
        "tierzeichen_aktuell": {
            "title": "Verteilung der Datenspenden auf die TikTok-Tierzeichen",
            "caption": (
                "Anteil der bisherigen Datenspenden nach zugewiesenem "
                "TikTok-Tierzeichen im laufenden Projekt. Die Verteilung ist "
                "unabhängig vom Bundesland-Filter der Partei-Grafiken.\n"
                f"{TIERZEICHEN_SOURCE_LINE}\n"
                f"{CREDIT_LINE}"
            ),
        },
        "tierzeichen_btw2025": {
            "title": (
                "Verteilung der Datenspenden auf die TikTok-Tierzeichen "
                "(Bundestagswahl 2025)"
            ),
            "caption": (
                "Vergleichsverteilung aus Datenspenden zur Bundestagswahl 2025. "
                "Unabhängig vom Bundesland-Filter der Partei-Grafiken.\n"
                f"{TIERZEICHEN_SOURCE_LINE}\n"
                f"{CREDIT_LINE}"
            ),
        },
    }


def nationwide_export_meta() -> dict[str, dict[str, str]]:
    """Captions for the unfiltered homepage / public-dev party plots."""
    if settings.DEBUG:
        video_stats: dict[str, Any] = {
            "start_date": "2026-07-01",
            "end_date": "2026-08-14",
            "n_accounts": 127,
        }
    else:
        video_stats = get_monitored_video_stats()
    return build_dashboard_export_meta(video_stats=video_stats)
