"""Fill in ``TikTokVideo.inferred_create_time`` where it is still empty.

New rows get it on creation (``ddcs.metadata.utils.new_video``). Rows that
donations or imports created before that have none until they are scraped
or delivered by the Research API; this command fills them in at once.

Semantics
---------
* Only rows without a value are touched; the value depends on the TikTok ID
  alone (``infer_publication_date_from_id``).
* ``updated_at`` is left alone: the field is not served by the prioritised
  video API, so moving it would only make ``updated_since`` report millions
  of unchanged videos.
* Works through the table in chunks, each committed on its own. It can be
  stopped and run again at any time.
* ``--dry-run`` only counts the rows that would be filled in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.management.base import BaseCommand, CommandError

from ddcs.metadata.models import TikTokVideo
from ddcs.metadata.utils import infer_publication_date_from_id

if TYPE_CHECKING:
    from django.core.management import CommandParser

# Progress is printed after this many chunks.
_PROGRESS_EVERY = 20


class Command(BaseCommand):
    help = (
        "Fill in inferred_create_time of videos that have none. "
        "Use --dry-run to only count them."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--chunk-size",
            type=int,
            default=5000,
            help="Rows read and written at a time (default: 5000).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only count the videos without a value; nothing is written.",
        )

    def handle(self, *args, chunk_size: int, dry_run: bool, **options) -> None:
        if chunk_size < 1:
            msg = "--chunk-size must be at least 1."
            raise CommandError(msg)

        missing = TikTokVideo.objects.filter(inferred_create_time__isnull=True)
        if dry_run:
            self.stdout.write(f"Videos without inferred_create_time: {missing.count()}")
            self.stdout.write("Dry run: nothing written.")
            return

        updated = chunks = 0
        last_pk = 0
        while True:
            videos = list(
                missing.filter(pk__gt=last_pk)
                .order_by("pk")
                .only("pk", "id_tiktok")[:chunk_size]
            )
            if not videos:
                break
            for video in videos:
                video.inferred_create_time = infer_publication_date_from_id(
                    video.id_tiktok
                )
            # ``bulk_update`` writes only the named field, not ``updated_at``.
            TikTokVideo.objects.bulk_update(videos, ["inferred_create_time"])
            updated += len(videos)
            last_pk = videos[-1].pk
            chunks += 1
            if chunks % _PROGRESS_EVERY == 0:
                self.stdout.write(f"{updated} videos updated ...")

        self.stdout.write(self.style.SUCCESS(f"Videos updated: {updated}"))
