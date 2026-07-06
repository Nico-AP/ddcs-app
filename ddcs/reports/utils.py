import csv
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from ddcs.reports.config import ACCOUNT_PARTY_MAPPING_CSV_PATH, N_TOP_VIDEOS

_TIKTOK_VIDEO_ID_RE = re.compile(r"/(?:video|photo)/(\d+)")


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


def parse_tiktok_video_id_from_url(url: str) -> int | None:
    match = _TIKTOK_VIDEO_ID_RE.search(url)
    if not match:
        return None
    return int(match.group(1))


def parse_tiktok_username_from_url(url: str) -> str:
    path = urlparse(url).path
    parts = [part for part in path.split("/") if part]
    if parts and parts[0].startswith("@"):
        return parts[0].removeprefix("@")
    return ""


def build_top_video_tiktok_url(video: dict) -> str:
    if url := video.get("tiktok_url"):
        return url
    video_id = video["video_id"]
    username = video.get("username") or ""
    if username:
        return f"https://www.tiktok.com/@{username}/video/{video_id}"
    return f"https://www.tiktok.com/share/video/{video_id}"


def build_tiktok_embed_url(video_id: int) -> str:
    return f"https://www.tiktok.com/player/v1/{video_id}?autoplay=0"


def enrich_top_videos_for_embed(videos: list[dict]) -> list[dict]:
    return [
        {
            **video,
            "tiktok_url": build_top_video_tiktok_url(video),
            "embed_url": build_tiktok_embed_url(video["video_id"]),
        }
        for video in videos[:N_TOP_VIDEOS]
    ]
