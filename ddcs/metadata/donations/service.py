"""What donations contribute to the metadata registry.

This module is the single ingestion path for donated data: it registers the
videos and users a donation contains and records, per video, that (and when)
donors watched it. Nothing else should create ``DonationVideoInfos`` rows.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from datetime import time as dt_time
from itertools import batched
from typing import TYPE_CHECKING, Any, NamedTuple

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from ddcs.metadata.donations.models import DonationVideoInfos
from ddcs.metadata.models import DataOrigins, TikTokUser, TikTokVideo
from ddcs.metadata.scraper.config import WATCH_WINDOW_END, WATCH_WINDOW_START
from ddcs.metadata.scraper.service import enqueue_watched_videos
from ddcs.metadata.utils import video_pks

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from ddcs.core.types import TikTokUserData

_RECORD_CHUNK_SIZE = 500


class WatchHistoryScan(NamedTuple):
    # TikTok ID -> the donor's most recent view of that video in the window.
    last_watched: dict[int, datetime]
    views_in_window: int
    # Records that could not be used: no parsed date or no video ID.
    skipped_records: int
    # TikTok ID -> the donor's most recent view of that video at any time,
    # inside the window or not. None if no view of it has a parsed date.
    last_seen: dict[int, datetime | None]


def scan_watch_history(
    watch_history: Iterable[Mapping[str, Any]] | None,
    start: date = WATCH_WINDOW_START,
    end: date = WATCH_WINDOW_END,
) -> WatchHistoryScan:
    """Find the videos one donor watched between ``start`` and ``end``.

    Both days are inclusive and taken in UTC, which is what donated
    timestamps are parsed as.
    """
    window_start = datetime.combine(start, dt_time.min, tzinfo=UTC)
    window_end = datetime.combine(end + timedelta(days=1), dt_time.min, tzinfo=UTC)

    last_watched: dict[int, datetime] = {}
    last_seen: dict[int, datetime | None] = {}
    views_in_window = skipped_records = 0
    for record in watch_history or []:
        video_id = record.get("video_id")
        watched_at = record.get("date")
        if isinstance(video_id, int):
            last_seen.setdefault(video_id, None)
        if not isinstance(video_id, int) or not isinstance(watched_at, datetime):
            skipped_records += 1
            continue
        if watched_at.tzinfo is None:
            watched_at = watched_at.replace(tzinfo=UTC)
        previous = last_seen[video_id]
        if previous is None or watched_at > previous:
            last_seen[video_id] = watched_at
        if not window_start <= watched_at < window_end:
            continue
        views_in_window += 1
        previous = last_watched.get(video_id)
        if previous is None or watched_at > previous:
            last_watched[video_id] = watched_at
    return WatchHistoryScan(last_watched, views_in_window, skipped_records, last_seen)


# TODO: Make this task async/convert to celery task.
def register_donation_metadata(data: TikTokUserData) -> None:
    """Creates DB entries based on donation data.

    Handles watch history, followed accounts, and liked videos. The watched
    videos are recorded as donated. If the scraper is enabled, those watched
    within the watch window are queued for scraping (those the Research API
    already covers are skipped).
    """
    # Watch history
    if data.watch_history:
        videos_to_add = [
            TikTokVideo(id_tiktok=record["video_id"], added_by=DataOrigins.DONATION)
            for record in data.watch_history
        ]
        TikTokVideo.objects.bulk_create(videos_to_add, ignore_conflicts=True)

    # Liked videos
    if data.liked_videos:
        videos_to_add = [
            TikTokVideo(id_tiktok=record["video_id"], added_by=DataOrigins.DONATION)
            for record in data.liked_videos
        ]
        TikTokVideo.objects.bulk_create(videos_to_add, ignore_conflicts=True)

    # Followed accounts
    if data.followed_accounts:
        user_names = {record.get("username") for record in data.followed_accounts} - {
            None
        }
        users_to_add = [
            TikTokUser(name=user_name, added_by=DataOrigins.DONATION)
            for user_name in user_names
        ]
        TikTokUser.objects.bulk_create(users_to_add, ignore_conflicts=True)

    scan = scan_watch_history(data.watch_history)
    record_donated_videos(scan.last_seen, scan.last_watched)

    if settings.TIKTOK_SCRAPER_ENABLED:
        # One more donation for every video it shows as watched in the window.
        enqueue_watched_videos(
            {
                video_id: (1, last_view)
                for video_id, last_view in scan.last_watched.items()
            }
        )


class DonatedVideosResult(NamedTuple):
    created: int
    # Existing rows whose last view moved to a later one.
    updated: int


def _later(current: datetime | None, candidate: datetime | None) -> datetime | None:
    return max(filter(None, (current, candidate)), default=None)


def record_donated_videos(
    last_seen: Mapping[int, datetime | None],
    last_seen_in_window: Mapping[int, datetime],
) -> DonatedVideosResult:
    """Record that the given videos occur in a donated watch history.

    ``last_seen`` maps the TikTok ID of every video in the watch history to
    the donor's most recent view of it (``None`` if no view has a usable
    date); ``last_seen_in_window`` holds the most recent view within the
    watch window, for the videos that have one.

    A video not recorded yet gets a row, a recorded one keeps the later of
    the stored and the given views. Recording the same donation again
    therefore changes nothing.

    Whenever a row is created or changed, ``updated_at`` of its
    ``TikTokVideo`` is moved as well: that is what the prioritised video API
    reports changes by (``updated_since``).

    Videos without a ``TikTokVideo`` row get one.
    """
    created = updated = 0

    for chunk in batched(last_seen, _RECORD_CHUNK_SIZE):
        pk_by_id = video_pks(chunk)
        existing = {
            infos.video_id: infos
            for infos in DonationVideoInfos.objects.filter(
                video_id__in=pk_by_id.values()
            )
        }

        now = timezone.now()
        new, changed = [], []
        for id_tiktok, pk in pk_by_id.items():
            seen_at = last_seen[id_tiktok]
            seen_in_window_at = last_seen_in_window.get(id_tiktok)
            infos = existing.get(pk)
            if infos is None:
                new.append(
                    DonationVideoInfos(
                        video_id=pk,
                        last_seen_at=seen_at,
                        last_seen_in_window_at=seen_in_window_at,
                    )
                )
                continue
            views = (
                _later(infos.last_seen_at, seen_at),
                _later(infos.last_seen_in_window_at, seen_in_window_at),
            )
            if views == (infos.last_seen_at, infos.last_seen_in_window_at):
                continue
            infos.last_seen_at, infos.last_seen_in_window_at = views
            # bulk_update does not apply auto_now.
            infos.updated_at = now
            changed.append(infos)

        with transaction.atomic():
            DonationVideoInfos.objects.bulk_create(new, ignore_conflicts=True)
            DonationVideoInfos.objects.bulk_update(
                changed, ["last_seen_at", "last_seen_in_window_at", "updated_at"]
            )
            TikTokVideo.objects.filter(
                pk__in=[infos.video_id for infos in (*new, *changed)]
            ).update(updated_at=now)
        created += len(new)
        updated += len(changed)

    return DonatedVideosResult(created, updated)
