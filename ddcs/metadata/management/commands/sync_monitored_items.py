"""Sync the monitored-items list from CSV files against the database.

This is the operational entry point for updating which TikTok users and
keywords are pulled by the daily Research API sync. The CSV files are
committed to the repository — every change goes through a PR, and the
git history is the audit trail.

File format (one entry per line):

    name              # priority defaults to 0
    name,priority     # explicit priority (int)

Blank lines and lines starting with ``#`` are ignored. Legacy plain-TXT
files (name-only, no header) are read the same way.

Semantics
---------
Running the command without ``--apply`` prints a plan and exits without
touching the DB. With ``--apply``:

* Names in the file but not in the DB are created (``monitor_api=True``,
  ``added_by=IMPORT``, priority from the file).
* Names present in the DB but missing from the file have
  ``monitor_api`` flipped to ``False`` — never hard-deleted, so
  historical sync attempts stay linked.
* Priority changes are applied to already-monitored rows.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING

from django.core.management.base import BaseCommand, CommandError

from ddcs.metadata.models import DataOrigins, Keyword, TikTokUser
from ddcs.metadata.research_api.utils.backfill_keywords import backfill_keywords

if TYPE_CHECKING:
    from django.core.management import CommandParser
    from django.db.models import Model


DEFAULT_USERS_FILE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "monitored_users.csv"
)
DEFAULT_KEYWORDS_FILE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "monitored_keywords.csv"
)


@dataclass(frozen=True)
class Entry:
    name: str
    priority: int


@dataclass
class Plan:
    to_create: list[Entry]
    to_reenable: list[tuple[Entry, int]]  # (entry, current_priority)
    to_update_priority: list[tuple[Entry, int]]  # (entry, current_priority)
    to_disable: list[str]

    def is_noop(self) -> bool:
        return not (
            self.to_create
            or self.to_reenable
            or self.to_update_priority
            or self.to_disable
        )


class Command(BaseCommand):
    help = (
        "Sync monitored TikTok users and keywords from CSV files. "
        "Prints a diff by default; use --apply to write it."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--users-file",
            type=Path,
            default=DEFAULT_USERS_FILE,
            help=f"Users CSV (default: {DEFAULT_USERS_FILE}).",
        )
        parser.add_argument(
            "--keywords-file",
            type=Path,
            default=DEFAULT_KEYWORDS_FILE,
            help=f"Keywords CSV (default: {DEFAULT_KEYWORDS_FILE}).",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the changes to the DB. Without it, only the plan is printed.",
        )
        parser.add_argument(
            "--skip-users",
            action="store_true",
            help="Skip the users file (only sync keywords).",
        )
        parser.add_argument(
            "--skip-keywords",
            action="store_true",
            help="Skip the keywords file (only sync users).",
        )

    def handle(
        self,
        *args,
        users_file: Path,
        keywords_file: Path,
        apply: bool,
        skip_users: bool,
        skip_keywords: bool,
        **options,
    ) -> None:
        did_anything = False

        if not skip_users:
            self._sync_kind(
                "users", users_file, TikTokUser, strip_hash=False, apply=apply
            )
            did_anything = True

        if not skip_keywords:
            self._sync_kind(
                "keywords",
                keywords_file,
                Keyword,
                strip_hash=False,
                apply=apply,
            )
            did_anything = True

        if not did_anything:
            msg = "Nothing to do — both --skip-* flags set."
            raise CommandError(msg)

        if not apply:
            self.stdout.write(
                self.style.WARNING(
                    "Dry run — no changes written. Re-run with --apply to commit."
                )
            )

    def _sync_kind(
        self,
        label: str,
        file: Path,
        model: type[Model],
        *,
        strip_hash: bool,
        apply: bool,
    ) -> None:
        if not file.is_file():
            msg = f"Input file not found: {file}"
            raise CommandError(msg)

        entries = _read_entries(file, strip_hash=strip_hash)
        plan = _build_plan(model, entries)

        self.stdout.write(self.style.HTTP_INFO(f"\n== {label} ({file}) =="))
        _print_plan(self.stdout, plan)

        if apply and not plan.is_noop():
            _apply_plan(model, plan)
            self.stdout.write(self.style.SUCCESS(f"Applied changes for {label}."))

    def _backfill_new_keywords(self, plan: Plan) -> None:
        newly_active_names = [e.name for e in plan.to_create] + [
            e.name for e, _ in plan.to_reenable
        ]
        if not newly_active_names:
            return

        keywords = list(Keyword.objects.filter(name__in=newly_active_names))
        self.stdout.write(
            self.style.HTTP_INFO(
                f"  Backfilling {len(keywords)} newly-monitored keyword(s) "
                f"against existing videos..."
            )
        )
        backfill_keywords(keywords)
        self.stdout.write(self.style.SUCCESS("  Backfill complete."))


def _read_entries(path: Path, *, strip_hash: bool) -> list[Entry]:
    """Parse ``name[,priority]`` per line. Supports plain-TXT (name only).

    Ignores blank lines, ``#`` comments, and duplicate names (first wins).
    """
    text = path.read_text(encoding="utf-8")

    seen: set[str] = set()
    entries: list[Entry] = []
    reader = csv.reader(StringIO(text))
    for row in reader:
        if not row:
            continue
        raw_name = row[0].strip()
        if strip_hash:
            raw_name = raw_name.lstrip("#")
        if not raw_name or raw_name.startswith("#") or raw_name in seen:
            continue
        priority = 0
        if len(row) > 1 and row[1].strip():
            try:
                priority = int(row[1].strip())
            except ValueError as exc:
                msg = f"Invalid priority for {raw_name!r} in {path}: {row[1]!r}"
                raise CommandError(msg) from exc
        seen.add(raw_name)
        entries.append(Entry(name=raw_name, priority=priority))
    return entries


def _build_plan(model: type[Model], entries: list[Entry]) -> Plan:
    wanted = {e.name: e for e in entries}
    existing = {
        row["name"]: row
        for row in model.objects.filter(name__in=wanted.keys()).values(
            "name", "monitor_api", "monitoring_priority_api"
        )
    }
    currently_monitored = set(
        model.objects.filter(monitor_api=True).values_list("name", flat=True)
    )

    to_create: list[Entry] = []
    to_reenable: list[tuple[Entry, int]] = []
    to_update_priority: list[tuple[Entry, int]] = []

    for entry in entries:
        row = existing.get(entry.name)
        if row is None:
            to_create.append(entry)
            continue
        if not row["monitor_api"]:
            to_reenable.append((entry, row["monitoring_priority_api"]))
        elif row["monitoring_priority_api"] != entry.priority:
            to_update_priority.append((entry, row["monitoring_priority_api"]))

    to_disable = sorted(currently_monitored - wanted.keys())

    return Plan(
        to_create=to_create,
        to_reenable=to_reenable,
        to_update_priority=to_update_priority,
        to_disable=to_disable,
    )


def _apply_plan(model: type[Model], plan: Plan) -> None:
    for entry in plan.to_create:
        model.objects.create(
            name=entry.name,
            monitor_api=True,
            monitoring_priority_api=entry.priority,
            added_by=DataOrigins.IMPORT,
        )
    for entry, _ in plan.to_reenable:
        model.objects.filter(name=entry.name).update(
            monitor_api=True, monitoring_priority_api=entry.priority
        )
    for entry, _ in plan.to_update_priority:
        model.objects.filter(name=entry.name).update(
            monitoring_priority_api=entry.priority
        )
    if plan.to_disable:
        model.objects.filter(name__in=plan.to_disable).update(monitor_api=False)


def _print_plan(stdout, plan: Plan) -> None:  # noqa: ANN001
    if plan.is_noop():
        stdout.write("  (no changes)")
        return
    if plan.to_create:
        stdout.write(f"  + create ({len(plan.to_create)}):")
        for e in plan.to_create:
            stdout.write(f"      {e.name}  priority={e.priority}")
    if plan.to_reenable:
        stdout.write(f"  ~ re-enable ({len(plan.to_reenable)}):")
        for e, cur_prio in plan.to_reenable:
            note = (
                f"priority={e.priority}"
                if cur_prio == e.priority
                else f"priority: {cur_prio} → {e.priority}"
            )
            stdout.write(f"      {e.name}  {note}")
    if plan.to_update_priority:
        stdout.write(f"  ~ priority ({len(plan.to_update_priority)}):")
        for e, cur_prio in plan.to_update_priority:
            stdout.write(f"      {e.name}  {cur_prio} → {e.priority}")
    if plan.to_disable:
        stdout.write(f"  - disable ({len(plan.to_disable)}):")
        for name in plan.to_disable:
            stdout.write(f"      {name}")
