"""Rebuild the donation infos from the stored donations.

Goes through the donations one at a time. Every video a donor watched,
liked or bookmarked has the matching counts of its ``DonationVideoInfos``
raised by one (or gets a row) and keeps the most recent interaction, at any
time and within the watch window.

Nothing is collected in memory: each donation is written to the database
before the next one is read, so the size of the run does not matter.

Because the command adds to the counts, it first resets them all to zero; a
run therefore always counts from scratch and can be repeated. Rows and
interaction times are kept, so the priorities derived from them stay as they
are while it runs. The counts are still not exact: donations processed while
it runs, or retried later, may be counted twice.

Known test participants (``EXCLUDED_PARTICIPANT_IDS``) are left out. See
docs/4_metadata.md.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from ddcs.datadonation.services import (
    get_video_donations,
    participants_with_video_donations,
)
from ddcs.metadata.donations.config import EXCLUDED_PARTICIPANT_IDS
from ddcs.metadata.donations.service import (
    record_donated_videos,
    reset_donation_counts,
    scan_donated_videos,
)
from ddcs.metadata.scraper.config import WATCH_WINDOW_END, WATCH_WINDOW_START

logger = logging.getLogger(__name__)

_PROGRESS_EVERY = 100


class Command(BaseCommand):
    help = (
        "Record the videos donors watched, liked or bookmarked: number of "
        "donors per kind of interaction and most recent interaction."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--start",
            type=date.fromisoformat,
            default=WATCH_WINDOW_START,
            help=f"First day of the watch window (default: {WATCH_WINDOW_START}).",
        )
        parser.add_argument(
            "--end",
            type=date.fromisoformat,
            default=WATCH_WINDOW_END,
            help=f"Last day of the watch window (default: {WATCH_WINDOW_END}).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only read the donations and report; change nothing.",
        )

    def handle(self, *args: Any, **options: Any) -> None:  # noqa: ANN401
        start, end, dry_run = options["start"], options["end"], options["dry_run"]
        if start > end:
            msg = f"--start ({start}) must not be after --end ({end})."
            raise CommandError(msg)

        counts_reset = None if dry_run else reset_donation_counts()

        donations_read = donations_unreadable = participants_excluded = 0
        watched = liked = bookmarked = in_window = 0
        created = updated = 0

        for participant in participants_with_video_donations().iterator():
            if participant.external_id in EXCLUDED_PARTICIPANT_IDS:
                participants_excluded += 1
                continue

            try:
                videos = scan_donated_videos(
                    get_video_donations(participant), start, end
                )
            except Exception:
                logger.exception(
                    "Could not read the donated videos of participant %s.",
                    participant.pk,
                )
                donations_unreadable += 1
                continue

            donations_read += 1
            for video in videos.values():
                watched += video.watched
                liked += video.liked
                bookmarked += video.bookmarked
                in_window += video.last_interaction_in_window_at is not None

            if not dry_run:
                result = record_donated_videos(videos)
                created += result.created
                updated += result.updated

            if donations_read % _PROGRESS_EVERY == 0:
                self.stdout.write(f"  {donations_read} donations read ...")

        self.stdout.write(
            f"Watch window: {start} to {end} (UTC, both days included)\n"
            f"Donations read: {donations_read}\n"
            f"Donations that could not be read: {donations_unreadable}\n"
            f"Test participants left out: {participants_excluded}\n"
            "Summed over donations:\n"
            f"  Videos watched: {watched}\n"
            f"  Videos liked: {liked}\n"
            f"  Videos bookmarked: {bookmarked}\n"
            f"  Videos with an interaction in the window: {in_window}"
        )
        if dry_run:
            self.stdout.write("Dry run: nothing was changed.")
            return

        self.stdout.write(
            f"Rows with counts reset: {counts_reset}\n"
            f"Rows created: {created}\n"
            f"Counts raised on existing rows: {updated}"
        )
        self.stdout.write(self.style.SUCCESS("Donation infos updated."))
