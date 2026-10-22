"""Import TikTok video links from a CSV file and queue the videos for scraping.

Meant for large lists of videos from outside the donations (e.g. millions of
links from a partner dataset).

File format: a header row and one column with the video link, named by
``--column`` (default ``link``). Other columns are ignored. Accepted values:

    https://www.tiktok.com/@user/video/7100000000000000001
    https://www.tiktok.com/@user/photo/7100000000000000001?lang=de
    7100000000000000001

Short links (``vm.tiktok.com/...``) can't be resolved without a request to
TikTok and are counted as unparseable, as are empty cells.

Semantics
---------
* Videos missing from the DB are created with ``added_by`` set to
  ``--origin``. Videos already in the DB keep their origin.
* With ``--origin DATAPODS``, every listed video, new or already in the DB,
  is marked ``in_datapods``, which ranks it like a donated video in the
  prioritised video API (see docs/4_metadata.md). Marking an existing video
  moves its ``updated_at``, as its priority may change.
* Each video gets a scrape target without a donation count or watch date,
  so it is queued after all donated videos (see docs/8_scraper.md).
  Targets that already exist keep their status and ranking; videos the
  Research API already covers are not queued.
* The file is read and written in chunks, each committed on its own. The
  import can be repeated: a second run changes nothing, so an interrupted
  one is simply started again. The scraper may keep running meanwhile.
* ``--dry-run`` only reads and parses the file.
"""

from __future__ import annotations

import csv
from itertools import batched, pairwise
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ddcs.metadata.models import DataOrigins, TikTokVideo
from ddcs.metadata.scraper.service import enqueue_donated_videos
from ddcs.metadata.utils import video_pks

if TYPE_CHECKING:
    from collections.abc import Iterator

    from django.core.management import CommandParser

# Path segments a video ID follows in a TikTok link.
_ID_SEGMENTS = frozenset({"video", "photo"})
# How many unparseable values are shown as examples.
_EXAMPLES = 20
# Progress is printed after this many chunks.
_PROGRESS_EVERY = 20


def _video_id(value: str) -> int | None:
    """The TikTok ID in a video link (or a bare ID), ``None`` if there is none."""
    value = value.strip()
    if value.isdigit():
        return int(value)
    segments = urlparse(value).path.strip("/").split("/")
    for previous, segment in pairwise(segments):
        if previous in _ID_SEGMENTS and segment.isdigit():
            return int(segment)
    return None


class Command(BaseCommand):
    help = (
        "Import TikTok video links from a CSV file and queue the videos for "
        "scraping. Use --dry-run to only parse the file."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("path", type=Path, help="CSV file with a header row.")
        parser.add_argument(
            "--origin",
            required=True,
            choices=DataOrigins.values,
            help="added_by of the videos this import creates (e.g. DATAPODS).",
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

    def handle(
        self,
        *args,
        path: Path,
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

        stats = dict.fromkeys(
            (
                "rows",
                "unparseable",
                "ids",
                "videos_created",
                "targets_created",
                "already_queued",
                "covered_by_api",
                "marked_datapods",
            ),
            0,
        )
        examples: list[str] = []

        with path.open(newline="", encoding="utf-8-sig") as f:
            for number, rows in enumerate(
                batched(self._values(f, column), chunk_size), start=1
            ):
                ids = set()
                for value in rows:
                    id_tiktok = _video_id(value)
                    if id_tiktok is None:
                        stats["unparseable"] += 1
                        if len(examples) < _EXAMPLES:
                            examples.append(value)
                    else:
                        ids.add(id_tiktok)
                stats["rows"] += len(rows)
                stats["ids"] += len(ids)

                if not dry_run and ids:
                    self._import(ids, DataOrigins(origin), stats)
                if number % _PROGRESS_EVERY == 0:
                    self.stdout.write(f"{stats['rows']} rows read ...")

        self._summary(stats, examples, dry_run=dry_run)

    @staticmethod
    def _values(f: Iterator[str], column: str) -> Iterator[str]:
        reader = csv.DictReader(f)
        if column not in (reader.fieldnames or []):
            msg = f"Column '{column}' not found; header: {reader.fieldnames}"
            raise CommandError(msg)
        for row in reader:
            yield row[column] or ""

    @staticmethod
    def _import(ids: set[int], origin: DataOrigins, stats: dict[str, int]) -> None:
        known = TikTokVideo.objects.filter(id_tiktok__in=ids).count()
        # Create the missing rows here, with the import's origin: the queue
        # would create them too, but as donated videos.
        video_pks(ids, added_by=origin)
        if origin == DataOrigins.DATAPODS:
            # ``update`` skips ``auto_now``: ``updated_at`` is how the
            # prioritised video API reports a changed priority.
            stats["marked_datapods"] += TikTokVideo.objects.filter(
                id_tiktok__in=ids, in_datapods=False
            ).update(in_datapods=True, updated_at=timezone.now())
        result = enqueue_donated_videos(dict.fromkeys(ids, (0, None)))
        stats["videos_created"] += len(ids) - known
        stats["targets_created"] += result.created
        stats["already_queued"] += result.updated
        stats["covered_by_api"] += result.covered_by_api

    def _summary(
        self, stats: dict[str, int], examples: list[str], *, dry_run: bool
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
        self.stdout.write(f"Videos created: {stats['videos_created']}")
        self.stdout.write(f"Marked as Datapods: {stats['marked_datapods']}")
        self.stdout.write(f"Scrape targets created: {stats['targets_created']}")
        self.stdout.write(f"Already queued: {stats['already_queued']}")
        self.stdout.write(
            f"Skipped, Research API has the video: {stats['covered_by_api']}"
        )
        self.stdout.write(self.style.SUCCESS("Import finished."))
