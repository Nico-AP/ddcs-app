import logging
from datetime import UTC, datetime
from typing import Any

from ddm.datadonation.models import DataDonation
from ddm.encryption.models import Decryption
from ddm.participation.models import Participant
from ddm.projects.models import DonationProject

from ddcs.core.types import TikTokUserData
from ddcs.datadonation.config import (
    COMMENTS_BP_NAME,
    FOLLOWED_BP_NAME,
    LIKED_VIDEOS_BP_NAME,
    SHARED_VIDEOS_BP_NAME,
    VIDEO_BOOKMARKS_BP_NAME,
    WATCH_HISTORY_BP_NAME,
)

logger = logging.getLogger(__name__)


_DECRYPTORS: dict[int, Decryption] = {}


def _get_decryptor(project: DonationProject) -> Decryption:
    """Load decryptor from cache or initialize."""
    if project.pk not in _DECRYPTORS:
        _DECRYPTORS[project.pk] = Decryption(project.secret, project.get_salt())
    return _DECRYPTORS[project.pk]


_BLUEPRINT_NAMES = [
    WATCH_HISTORY_BP_NAME,
    FOLLOWED_BP_NAME,
    LIKED_VIDEOS_BP_NAME,
    SHARED_VIDEOS_BP_NAME,
    VIDEO_BOOKMARKS_BP_NAME,
    COMMENTS_BP_NAME,
]

_BLUEPRINT_NAMES_INCL_BACKUPS = [
    n for bp in _BLUEPRINT_NAMES for n in (bp, bp + "_txt", bp + "_old")
]


def _get_donation_data(participant: Participant) -> dict:
    """Fetch and decrypt the participant's successful donations.

    Returns a dict keyed by blueprint name (watch history, followed accounts,
    liked videos) with the decrypted records as values. It checks whether
    the base blueprint or the backup blueprint has been extracted and includes
    it under the base name. Blueprints without a successful donation map to ``None``.
    If both the base and "_txt" backup variant succeeded, the base variant is used.
    """
    donations = DataDonation.objects.filter(
        participant=participant,
        blueprint__name__in=_BLUEPRINT_NAMES_INCL_BACKUPS,
        data_extraction_state=DataDonation.DataExtractionState.DATA_EXTRACTED,
    ).select_related("blueprint")

    project = participant.project
    decryptor = _get_decryptor(project)
    donations_by_blueprint = {
        donation.blueprint.name: donation.get_decrypted_data(
            project.secret,
            project.get_salt(),
            decryptor=decryptor,
        )
        for donation in donations
    }
    return {
        bp_name: donations_by_blueprint.get(
            bp_name,
            donations_by_blueprint.get(
                bp_name + "_txt", donations_by_blueprint.get(bp_name + "_old")
            ),
        )
        for bp_name in _BLUEPRINT_NAMES
    }


_KEY_NORMALISATION = {
    "date": "date",
    "(d|d)ate": "date",
    "link": "link",
    "(l|l)ink": "link",
}


def _normalise_key(key: str) -> str:
    """Lowercase key and resolve known variants to their standard form."""
    lowered = key.lower()
    return _KEY_NORMALISATION.get(lowered, lowered)


_DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d %H:%M:%S UTC",  # e.g. "2026-05-08 13:15:38 UTC"
    "%Y-%m-%d %H:%M:%S",  # e.g. "2026-05-08 13:15:38"
    "%Y-%m-%dT%H:%M:%S",  # ISO-ish without tz
)


def _parse_date(value: str) -> datetime | str:
    """Parse a donated date string into a tz-aware UTC datetime.

    Returns the original string unchanged if no known format matches.
    Callers are responsible for logging/counting failures.
    """
    stripped = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(stripped, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue

    try:
        parsed = datetime.fromisoformat(stripped)
    except ValueError:
        return value
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _normalise_value(key: str, value: Any) -> Any:  # noqa: ANN401
    if key == "date" and isinstance(value, str):
        return _parse_date(value)
    return value


def _clean_record(record: dict[str, Any]) -> dict[str, Any]:
    """Normalise all keys and values in a single record."""
    cleaned_record = {}
    for key, value in record.items():
        normalised_key = _normalise_key(key)
        normalised_value = _normalise_value(normalised_key, value)
        cleaned_record[normalised_key] = normalised_value
    return cleaned_record


def _clean_records(records: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """Clean a list of records, returning None if the input is None."""
    if records is None:
        return None
    return [_clean_record(record) for record in records]


def _clean_donated_data(data: dict[str, Any]) -> dict[str, Any]:
    """
    Clean donated data by normalising record keys:
    - Lowercase all keys
    - Normalise regex-like variants e.g. "(D|d)ate" -> "date", "(L|l)ink" -> "link"
    - Convert "date" values to datetime objects where possible

    Args:
        data: Raw donated data keyed by blueprint name, each value a list of records.

    Returns:
        Cleaned data with normalised keys.
    """
    cleaned = {
        blueprint_name: _clean_records(records)
        for blueprint_name, records in data.items()
    }

    unparseable = sum(
        1
        for records in cleaned.values()
        if records
        for record in records
        if isinstance(record.get("date"), str)
    )
    if unparseable:
        logger.warning("Failed to parse %d date value(s) during cleaning", unparseable)

    return cleaned


def _extract_id_from_link(link: str) -> int | None:
    try:
        return int(link.strip("/").split("/")[-1])
    except ValueError:
        return None


def _add_video_id_to_record(record: dict[str, Any]) -> dict[str, Any]:
    """Extract video ID from link and add it to the record under 'video_id' key."""
    record_with_link = dict(record)
    if not record_with_link.get("link") and (
        shared_content := record_with_link.get("sharedcontent")
    ):
        record_with_link["link"] = shared_content
    if link := record_with_link.get("link"):
        return {**record_with_link, "video_id": _extract_id_from_link(link)}
    return record_with_link


def _map_video_records(
    records: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    if records is None:
        return None
    return [_add_video_id_to_record(record) for record in records]


def _map_to_user_data(data: dict[str, Any]) -> TikTokUserData:
    """Map raw blueprint data to a TikTokUserData dataclass."""
    return TikTokUserData(
        watch_history=_map_video_records(data.get(WATCH_HISTORY_BP_NAME)),
        followed_accounts=data.get(FOLLOWED_BP_NAME),
        liked_videos=_map_video_records(data.get(LIKED_VIDEOS_BP_NAME)),
        shared_videos=_map_video_records(data.get(SHARED_VIDEOS_BP_NAME)),
        video_bookmarks=_map_video_records(data.get(VIDEO_BOOKMARKS_BP_NAME)),
        comments=_map_video_records(data.get(COMMENTS_BP_NAME)),
    )


def get_user_data(participant: Participant) -> TikTokUserData:
    data = _get_donation_data(participant)
    data = _clean_donated_data(data)
    return _map_to_user_data(data)


def post_process_donation(participant: Participant) -> None:
    from ddcs.datadonation.tasks import process_donation  # noqa: PLC0415

    process_donation.delay(participant.pk)
