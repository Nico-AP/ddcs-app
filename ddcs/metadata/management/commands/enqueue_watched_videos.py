"""Fill the scrape queue from the donated watch histories.

Goes through the donations one at a time. For every video a donor watched
within the watch window, the video's scrape target has its donor count
raised by one (or is created) and keeps the most recent view. The scraper
first works off the videos many donors watched recently, then the rest by
most recent view.

Nothing is collected in memory: each donation is written to the database
before the next one is read, so the size of the run does not matter.

Because the command adds to the counts, it first resets them all to zero;
a run therefore always counts from scratch and can be repeated. The counts
are still not exact: donations processed while it runs, or retried later,
may be counted twice. That is accepted, the counts only rank the queue.
Nothing already scraped is queued again. See docs/8_scraper.md.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from ddcs.datadonation.services import (
    get_watch_history,
    participants_with_watch_history,
)
from ddcs.metadata.scraper.config import WATCH_WINDOW_END, WATCH_WINDOW_START
from ddcs.metadata.scraper.service import (
    enqueue_watched_videos,
    reset_watch_ranking,
    scan_watch_history,
)

logger = logging.getLogger(__name__)

_PROGRESS_EVERY = 100


class Command(BaseCommand):
    help = (
        "Queue the videos donors watched within the watch window for scraping, "
        "recording number of donors and most recent view."
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
            "--keep-counts",
            action="store_true",
            help=(
                "Do not reset the existing counts first; add to them. Every "
                "donation read is then counted on top of what is stored."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only read the watch histories and report; change nothing.",
        )

    def handle(self, *args: Any, **options: Any) -> None:  # noqa: ANN401
        start, end, dry_run = options["start"], options["end"], options["dry_run"]
        if start > end:
            msg = f"--start ({start}) must not be after --end ({end})."
            raise CommandError(msg)

        targets_reset = None
        if not dry_run and not options["keep_counts"]:
            targets_reset = reset_watch_ranking()

        donations_read = donations_unreadable = 0
        views_in_window = skipped_records = watched_videos = 0
        created = updated = covered_by_api = 0

        for participant in participants_with_watch_history().iterator():
            try:
                scan = scan_watch_history(get_watch_history(participant), start, end)
            except Exception:
                logger.exception(
                    "Could not read the watch history of participant %s.",
                    participant.pk,
                )
                donations_unreadable += 1
                continue

            donations_read += 1
            views_in_window += scan.views_in_window
            skipped_records += scan.skipped_records
            watched_videos += len(scan.last_watched)

            if not dry_run:
                result = enqueue_watched_videos(
                    {
                        video_id: (1, watched_at)
                        for video_id, watched_at in scan.last_watched.items()
                    }
                )
                created += result.created
                updated += result.updated
                covered_by_api += result.covered_by_api

            if donations_read % _PROGRESS_EVERY == 0:
                self.stdout.write(f"  {donations_read} donations read ...")

        self.stdout.write(
            f"Watch window: {start} to {end} (UTC, both days included)\n"
            f"Donations read: {donations_read}\n"
            f"Donations that could not be read: {donations_unreadable}\n"
            f"Views in the window: {views_in_window}\n"
            f"Records skipped (no date or no video ID): {skipped_records}\n"
            f"Videos watched in the window, summed over donations: {watched_videos}"
        )
        if dry_run:
            self.stdout.write(
                "Dry run: nothing was changed. The number of distinct videos, and "
                "so of targets, is at most the sum above."
            )
            return

        if targets_reset is not None:
            self.stdout.write(f"Counts reset on existing targets: {targets_reset}")
        self.stdout.write(
            f"Targets created: {created}\n"
            f"Counts raised on existing targets: {updated}\n"
            f"Skipped, Research API has the video (per donation): {covered_by_api}"
        )
        self.stdout.write(self.style.SUCCESS("Scrape queue updated."))
