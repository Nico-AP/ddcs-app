"""Give TikTok videos a priority by hand, or take it away again.

The manual priority replaces the derived one in the prioritised video API
(see docs/4_metadata.md), up or down: 5 or higher ranks a video above every
derived priority, 1 to 4 pins it to one of them, whatever the donations, the
Datapods or the Research API say later.

File format: a header row and one column with the video link,
named by ``--column`` (default ``link``). Other columns are ignored.
Links and bare IDs are accepted.

Semantics
---------
* ``--priority N`` gives every listed video priority ``N``, also videos that
  had another manual priority. Videos missing from the DB are created with
  ``added_by`` set to ``--origin`` and queued for scraping like an
  ``import_video_links`` import (after all donated videos).
* ``--remove`` takes the manual priority away from the listed videos; they
  fall back to their derived priority. Nothing is created or queued.
* Every video whose priority changes has its ``updated_at`` moved, so the
  change shows up in ``updated_since``.
* The file is read and written in chunks, each committed on its own. A
  second run changes nothing, so an interrupted one is simply started again.
* ``--dry-run`` only reads and parses the file.
"""

from __future__ import annotations

import csv
from itertools import batched
from pathlib import Path
from typing import TYPE_CHECKING

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ddcs.metadata.models import DataOrigins, TikTokVideo
from ddcs.metadata.priority import MANUAL_PRIORITY_MIN
from ddcs.metadata.scraper.service import enqueue_donated_videos
from ddcs.metadata.utils import video_id_from_link, video_pks

if TYPE_CHECKING:
    from collections.abc import Iterator

    from django.core.management import CommandParser

# How many unparseable values are shown as examples.
_EXAMPLES = 20


class Command(BaseCommand):
    help = (
        "Give the TikTok videos listed in a CSV file a manual priority "
        f"(--priority N, N >= {MANUAL_PRIORITY_MIN}), or take it away (--remove)."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("path", type=Path, help="CSV file with a header row.")
        action = parser.add_mutually_exclusive_group(required=True)
        action.add_argument(
            "--priority",
            type=int,
            help=f"The priority to give the videos, {MANUAL_PRIORITY_MIN} or higher.",
        )
        action.add_argument(
            "--remove",
            action="store_true",
            help="Take the manual priority away from the videos.",
        )
        parser.add_argument(
            "--origin",
            default=DataOrigins.IMPORT,
            choices=DataOrigins.values,
            help="added_by of the videos this command creates (default: IMPORT).",
        )
        parser.add_argument(
            "--column",
            default="link",
            help="Header of the column holding the links (default: link).",
        )
        parser.add_argument(
            "--chunk-size",
            type=int,
            default=5000,
            help="Rows read and written at a time (default: 5000).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only read and parse the file; nothing is written.",
        )

    def handle(  # noqa: PLR0913
        self,
        *args,
        path: Path,
        priority: int | None,
        remove: bool,
        origin: str,
        column: str,
        chunk_size: int,
        dry_run: bool,
        **options,
    ) -> None:
        if not path.is_file():
            msg = f"No such file: {path}"
            raise CommandError(msg)
        if chunk_size < 1:
            msg = "--chunk-size must be at least 1."
            raise CommandError(msg)
        if priority is not None and priority < MANUAL_PRIORITY_MIN:
            msg = f"--priority must be at least {MANUAL_PRIORITY_MIN}."
            raise CommandError(msg)

        stats = dict.fromkeys(
            (
                "rows",
                "unparseable",
                "ids",
                "videos_created",
                "changed",
                "unchanged",
                "not_in_db",
                "targets_created",
                "already_queued",
                "covered_by_api",
            ),
            0,
        )
        examples: list[str] = []

        with path.open(newline="", encoding="utf-8-sig") as f:
            for rows in batched(_values(f, column), chunk_size):
                ids = set()
                for value in rows:
                    id_tiktok = video_id_from_link(value)
                    if id_tiktok is None:
                        stats["unparseable"] += 1
                        if len(examples) < _EXAMPLES:
                            examples.append(value)
                    else:
                        ids.add(id_tiktok)
                stats["rows"] += len(rows)
                stats["ids"] += len(ids)

                if dry_run or not ids:
                    continue
                if remove:
                    self._remove(ids, stats)
                else:
                    self._set(ids, priority, DataOrigins(origin), stats)

        self._summary(stats, examples, remove=remove, dry_run=dry_run)

    @staticmethod
    def _set(
        ids: set[int], priority: int, origin: DataOrigins, stats: dict[str, int]
    ) -> None:
        known = TikTokVideo.objects.filter(id_tiktok__in=ids).count()
        video_pks(ids, added_by=origin)
        # ``update`` skips ``auto_now``: ``updated_at`` is how the
        # prioritised video API reports a changed priority.
        changed = (
            TikTokVideo.objects.filter(id_tiktok__in=ids)
            .exclude(manual_priority=priority)
            .update(manual_priority=priority, updated_at=timezone.now())
        )
        result = enqueue_donated_videos(dict.fromkeys(ids, (0, None)))
        stats["videos_created"] += len(ids) - known
        stats["changed"] += changed
        stats["unchanged"] += len(ids) - changed
        stats["targets_created"] += result.created
        stats["already_queued"] += result.updated + result.unchanged
        stats["covered_by_api"] += result.covered_by_api

    @staticmethod
    def _remove(ids: set[int], stats: dict[str, int]) -> None:
        known = TikTokVideo.objects.filter(id_tiktok__in=ids).count()
        changed = TikTokVideo.objects.filter(
            id_tiktok__in=ids, manual_priority__isnull=False
        ).update(manual_priority=None, updated_at=timezone.now())
        stats["not_in_db"] += len(ids) - known
        stats["changed"] += changed
        stats["unchanged"] += known - changed

    def _summary(
        self,
        stats: dict[str, int],
        examples: list[str],
        *,
        remove: bool,
        dry_run: bool,
    ) -> None:
        self.stdout.write(f"Rows read: {stats['rows']}")
        self.stdout.write(f"Unparseable: {stats['unparseable']}")
        for example in examples:
            self.stdout.write(f"  e.g. {example!r}")
        # Duplicates are only dropped within a chunk, not across the file.
        self.stdout.write(f"Video IDs: {stats['ids']}")
        if dry_run:
            self.stdout.write("Dry run: nothing written.")
            return
        if remove:
            self.stdout.write(f"Manual priority removed: {stats['changed']}")
            self.stdout.write(f"Had none: {stats['unchanged']}")
            self.stdout.write(f"Not in the DB: {stats['not_in_db']}")
        else:
            self.stdout.write(f"Videos created: {stats['videos_created']}")
            self.stdout.write(f"Priority set: {stats['changed']}")
            self.stdout.write(f"Already had it: {stats['unchanged']}")
            self.stdout.write(f"Scrape targets created: {stats['targets_created']}")
            self.stdout.write(f"Already queued: {stats['already_queued']}")
            self.stdout.write(
                f"Skipped, Research API has the video: {stats['covered_by_api']}"
            )
        self.stdout.write(self.style.SUCCESS("Done."))


def _values(f: Iterator[str], column: str) -> Iterator[str]:
    reader = csv.DictReader(f)
    if column not in (reader.fieldnames or []):
        msg = f"Column '{column}' not found; header: {reader.fieldnames}"
        raise CommandError(msg)
    for row in reader:
        yield row[column] or ""
