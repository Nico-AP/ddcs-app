from pathlib import Path

from django.core.management import CommandParser
from django.core.management.base import BaseCommand, CommandError

from ddcs.metadata.models import DataOrigins, TikTokUser

DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "tiktok_users_to_monitor.txt"
)


class Command(BaseCommand):
    help = (
        "Import TikTok usernames from a newline-delimited text file and mark them "
        "as monitored by the Research API."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--file",
            type=Path,
            default=DEFAULT_FIXTURE,
            help=f"Path to the input file. Defaults to {DEFAULT_FIXTURE}.",
        )
        parser.add_argument(
            "--priority",
            type=int,
            default=0,
            help="Monitoring priority assigned to newly created users.",
        )

    def handle(self, *args, file: Path, priority: int, **options) -> None:
        if not file.is_file():
            msg = f"Input file not found: {file}"
            raise CommandError(msg)

        names = _read_names(file)
        if not names:
            self.stdout.write("No usernames found in input file.")
            return

        created, updated = 0, 0
        for name in names:
            _, was_created = TikTokUser.objects.update_or_create(
                name=name,
                defaults={
                    "monitor_api": True,
                },
                create_defaults={
                    "monitor_api": True,
                    "monitoring_priority_api": priority,
                    "added_by": DataOrigins.IMPORT,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {len(names)} usernames "
                f"({created} created, {updated} updated)."
            )
        )


def _read_names(path: Path) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        name = raw.strip()
        if not name or name.startswith("#") or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names
