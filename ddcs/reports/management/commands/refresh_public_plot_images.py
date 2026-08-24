from django.core.management import BaseCommand, CommandError, CommandParser

from ddcs.reports.plots.public_plot_images import (
    PUBLIC_PLOT_IMAGE_SLUGS,
    refresh_public_plot_images,
    write_public_plot_png,
)


class Command(BaseCommand):
    help = "Write homepage public plots to MEDIA_ROOT/public-plots/*.png for embedding."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--slug",
            choices=PUBLIC_PLOT_IMAGE_SLUGS,
            help="Write a single plot instead of both.",
        )

    def handle(self, *args, **options) -> None:
        slug = options.get("slug")
        try:
            if slug:
                paths = [write_public_plot_png(slug)]
            else:
                paths = refresh_public_plot_images()
        except (OSError, RuntimeError, ValueError) as exc:
            msg = str(exc)
            raise CommandError(msg) from exc
        if not paths:
            error = "No plot PNGs were written."
            raise CommandError(error)
        for path in paths:
            self.stdout.write(self.style.SUCCESS(str(path)))
