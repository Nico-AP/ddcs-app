"""Queue existing TikTok videos for scraping.

New donations queue their videos automatically (see
``ddcs.metadata.services.register_donation_metadata``). This command is the
one-off counterpart for videos that were already in the database: it walks
the videos of one data origin and queues those without Research API infos.

Safe to re-run: videos that are already queued are left as they are.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from ddcs.metadata.models import DataOrigins, TikTokVideo
from ddcs.metadata.scraper.service import enqueue_video_pks

_CHUNK_SIZE = 5000


class Command(BaseCommand):
    help = "Queue existing TikTok videos without Research API infos for scraping."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--origin",
            choices=DataOrigins.values,
            default=DataOrigins.DONATION,
            help="Only consider videos added by this data origin (default: DONATION).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Stop after queueing this many videos.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only report how many videos would be considered; queue nothing.",
        )

    def handle(self, *args: Any, **options: Any) -> None:  # noqa: ANN401
        limit = options["limit"]
        videos = TikTokVideo.objects.filter(added_by=options["origin"])

        if options["dry_run"]:
            self.stdout.write(
                f"{videos.count()} video(s) with origin {options['origin']} would be "
                "checked; those without Research API infos that are not queued "
                "yet would be queued. Nothing was changed."
            )
            return

        queued = 0
        last_pk = 0
        while limit is None or queued < limit:
            # With --limit, never look at more videos than may still be queued.
            size = _CHUNK_SIZE if limit is None else min(_CHUNK_SIZE, limit - queued)
            chunk = list(
                videos.filter(pk__gt=last_pk)
                .order_by("pk")
                .values_list("pk", flat=True)[:size]
            )
            if not chunk:
                break
            last_pk = chunk[-1]
            queued += enqueue_video_pks(chunk)

        self.stdout.write(self.style.SUCCESS(f"Queued {queued} video(s) for scraping."))
