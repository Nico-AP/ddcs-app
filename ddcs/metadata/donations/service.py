"""What donations contribute to the metadata registry.

This module is the single ingestion path for donated data: it registers the
videos and users a donation contains, records, per video, how many donors
watched, liked or bookmarked it and when, and queues the videos for scraping.
Nothing else should create ``DonationVideoInfos`` rows.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from datetime import time as dt_time
from itertools import batched
from typing import TYPE_CHECKING, NamedTuple

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ddcs.metadata.donations.models import DonationVideoInfos
from ddcs.metadata.models import DataOrigins, TikTokUser, TikTokVideo
from ddcs.metadata.scraper.config import WATCH_WINDOW_END, WATCH_WINDOW_START
from ddcs.metadata.scraper.service import enqueue_donated_videos
from ddcs.metadata.utils import new_video, video_pks

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ddcs.core.types import TikTokUserData

_RECORD_CHUNK_SIZE = 500
_RECORDED_FIELDS = [
    "watched_count",
    "liked_count",
    "bookmarked_count",
    "last_interaction_at",
    "last_interaction_in_window_at",
    "updated_at",
]


def _window_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """The window from ``start`` to ``end``, both days included, in UTC."""
    return (
        datetime.combine(start, dt_time.min, tzinfo=UTC),
        datetime.combine(end + timedelta(days=1), dt_time.min, tzinfo=UTC),
    )


def _later(current: datetime | None, candidate: datetime | None) -> datetime | None:
    return max(filter(None, (current, candidate)), default=None)


class VideoInteractions(NamedTuple):
    """What one donation shows about one video."""

    watched: bool
    liked: bool
    bookmarked: bool
    # Most recent view, like or bookmark; None if none of them has a usable
    # date.
    last_interaction_at: datetime | None
    # The same, restricted to the watch window.
    last_interaction_in_window_at: datetime | None


# Kind of interaction -> the field of ``TikTokUserData`` that lists it.
_INTERACTION_SOURCES = {
    "watched": "watch_history",
    "liked": "liked_videos",
    "bookmarked": "video_bookmarks",
}


def scan_donated_videos(
    data: TikTokUserData,
    start: date = WATCH_WINDOW_START,
    end: date = WATCH_WINDOW_END,
) -> dict[int, VideoInteractions]:
    """Find the videos one donor watched, liked or bookmarked.

    Returns, per TikTok ID, which of the three the donation shows and when
    the donor last interacted with the video, at any time and within the
    window from ``start`` to ``end`` (both days included, UTC). A record
    without a usable date still counts as an interaction; records without a
    video ID are ignored.
    """
    window_start, window_end = _window_bounds(start, end)

    kinds: dict[int, set[str]] = {}
    last: dict[int, datetime] = {}
    last_in_window: dict[int, datetime] = {}
    for kind, source in _INTERACTION_SOURCES.items():
        for record in getattr(data, source) or []:
            video_id = record.get("video_id")
            if not isinstance(video_id, int):
                continue
            kinds.setdefault(video_id, set()).add(kind)

            interacted_at = record.get("date")
            if not isinstance(interacted_at, datetime):
                continue
            if interacted_at.tzinfo is None:
                interacted_at = interacted_at.replace(tzinfo=UTC)
            last[video_id] = _later(last.get(video_id), interacted_at)
            if window_start <= interacted_at < window_end:
                last_in_window[video_id] = _later(
                    last_in_window.get(video_id), interacted_at
                )

    return {
        video_id: VideoInteractions(
            watched="watched" in video_kinds,
            liked="liked" in video_kinds,
            bookmarked="bookmarked" in video_kinds,
            last_interaction_at=last.get(video_id),
            last_interaction_in_window_at=last_in_window.get(video_id),
        )
        for video_id, video_kinds in kinds.items()
    }


# TODO: Make this task async/convert to celery task.
def register_donation_metadata(data: TikTokUserData) -> None:
    """Creates DB entries based on donation data.

    Handles watch history, followed accounts, liked and bookmarked videos.
    The watched, liked and bookmarked videos are recorded as donated. If the
    scraper is enabled, those with such an interaction within the watch
    window are queued for scraping (those the Research API already covers
    are skipped).
    """
    # Watch history
    if data.watch_history:
        videos_to_add = [
            new_video(record["video_id"], DataOrigins.DONATION)
            for record in data.watch_history
        ]
        TikTokVideo.objects.bulk_create(videos_to_add, ignore_conflicts=True)

    # Liked videos
    if data.liked_videos:
        videos_to_add = [
            new_video(record["video_id"], DataOrigins.DONATION)
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

    videos = scan_donated_videos(data)
    record_donated_videos(videos)

    if settings.TIKTOK_SCRAPER_ENABLED:
        enqueue_donated_videos(queue_entries(videos))


def queue_entries(
    videos: Mapping[int, VideoInteractions],
) -> dict[int, tuple[int, datetime]]:
    """What one donation adds to the scrape queue.

    Every video the donation shows as watched, liked or bookmarked within
    the watch window, as ``enqueue_donated_videos`` takes it: TikTok ID ->
    (one more donation, most recent interaction in the window).
    """
    return {
        video_id: (1, video.last_interaction_in_window_at)
        for video_id, video in videos.items()
        if video.last_interaction_in_window_at is not None
    }


class DonatedVideosResult(NamedTuple):
    created: int
    # Existing rows whose counts were raised.
    updated: int


def record_donated_videos(
    videos: Mapping[int, VideoInteractions],
) -> DonatedVideosResult:
    """Record the videos one donation shows as watched, liked or bookmarked.

    ``videos`` is what :func:`scan_donated_videos` returns for the donation.
    A video not recorded yet gets a row. For every video, the count of each
    kind of interaction the donation shows is raised by one, and the later
    of the stored and the given interaction times is kept.

    This only ever adds: calling it twice for the same donation counts that
    donation twice. :func:`reset_donation_counts` starts over.

    ``updated_at`` of the ``TikTokVideo`` is moved when a row is created or
    an interaction time moves: that is what the prioritised video API
    reports changes by (``updated_since``). A change of counts alone does
    not move it, as the counts do not affect what that API serves.

    Videos without a ``TikTokVideo`` row get one.
    """
    created = updated = 0

    for chunk in batched(videos, _RECORD_CHUNK_SIZE):
        pk_by_id = video_pks(chunk)
        existing = {
            infos.video_id: infos
            for infos in DonationVideoInfos.objects.filter(
                video_id__in=pk_by_id.values()
            )
        }

        now = timezone.now()
        new, changed, changed_video_pks = [], [], []
        for id_tiktok, pk in pk_by_id.items():
            video = videos[id_tiktok]
            infos = existing.get(pk)
            if infos is None:
                new.append(
                    DonationVideoInfos(
                        video_id=pk,
                        watched_count=int(video.watched),
                        liked_count=int(video.liked),
                        bookmarked_count=int(video.bookmarked),
                        last_interaction_at=video.last_interaction_at,
                        last_interaction_in_window_at=(
                            video.last_interaction_in_window_at
                        ),
                    )
                )
                changed_video_pks.append(pk)
                continue

            infos.watched_count += int(video.watched)
            infos.liked_count += int(video.liked)
            infos.bookmarked_count += int(video.bookmarked)
            interactions = (
                _later(infos.last_interaction_at, video.last_interaction_at),
                _later(
                    infos.last_interaction_in_window_at,
                    video.last_interaction_in_window_at,
                ),
            )
            if interactions != (
                infos.last_interaction_at,
                infos.last_interaction_in_window_at,
            ):
                (
                    infos.last_interaction_at,
                    infos.last_interaction_in_window_at,
                ) = interactions
                changed_video_pks.append(pk)
            # bulk_update does not apply auto_now.
            infos.updated_at = now
            changed.append(infos)

        with transaction.atomic():
            DonationVideoInfos.objects.bulk_create(new, ignore_conflicts=True)
            DonationVideoInfos.objects.bulk_update(changed, _RECORDED_FIELDS)
            TikTokVideo.objects.filter(pk__in=changed_video_pks).update(updated_at=now)
        created += len(new)
        updated += len(changed)

    return DonatedVideosResult(created, updated)


def purge_unbacked_donation_infos() -> int:
    """Delete the rows no donation backs any more.

    These are the rows whose counts are all zero after the donations were
    counted from scratch: their donors' donations are gone, or belong to
    participants that are left out. Only meaningful right after a complete
    recount; while counts are being rebuilt, zero does not mean "no donor".

    The videos stop counting as donated, so ``updated_at`` of their
    ``TikTokVideo`` is moved for the change to be reported. Scrape targets
    are not touched. Works in small steps. Returns the number of rows
    deleted.
    """
    unbacked = DonationVideoInfos.objects.filter(
        watched_count=0, liked_count=0, bookmarked_count=0
    )
    purged = 0
    while True:
        rows = list(unbacked.values_list("pk", "video_id")[:_RECORD_CHUNK_SIZE])
        if not rows:
            return purged
        with transaction.atomic():
            deleted, _ = DonationVideoInfos.objects.filter(
                pk__in=[pk for pk, _ in rows]
            ).delete()
            TikTokVideo.objects.filter(
                pk__in=[video_pk for _, video_pk in rows]
            ).update(updated_at=timezone.now())
        purged += deleted


def reset_donation_counts() -> int:
    """Set the counts of every row back to zero.

    Used before the donations are counted from scratch. Rows, interaction
    times and every ``updated_at`` are left alone, so priorities derived
    from them do not change while the counts are rebuilt. Works in small
    steps. Returns the number of rows reset.
    """
    counted = DonationVideoInfos.objects.filter(
        Q(watched_count__gt=0) | Q(liked_count__gt=0) | Q(bookmarked_count__gt=0)
    )
    reset = 0
    while True:
        pks = list(counted.values_list("pk", flat=True)[:_RECORD_CHUNK_SIZE])
        if not pks:
            return reset
        reset += DonationVideoInfos.objects.filter(pk__in=pks).update(
            watched_count=0, liked_count=0, bookmarked_count=0
        )
