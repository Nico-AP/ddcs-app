import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from ddcs.metadata.models import DataOrigins, TikTokVideo
from ddcs.metadata.priority import annotate_priority
from ddcs.metadata.scraper.models import ScrapeTarget


class SetManualPriorityTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "videos.csv"
        self.long_ago = timezone.now() - timedelta(days=2)

    def _write(self, *rows: str, header: str = "link") -> None:
        self.path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")

    def _run(self, *args: str) -> str:
        out = StringIO()
        call_command("set_manual_priority", str(self.path), *args, stdout=out)
        return out.getvalue()

    def _video(self, id_tiktok: int, manual_priority: int | None = None) -> None:
        TikTokVideo.objects.create(
            id_tiktok=id_tiktok,
            added_by=DataOrigins.DONATION,
            manual_priority=manual_priority,
        )

    def _make_old(self) -> None:
        TikTokVideo.objects.update(updated_at=self.long_ago)

    def _manual(self) -> dict[int, int | None]:
        return dict(TikTokVideo.objects.values_list("id_tiktok", "manual_priority"))

    def _moved(self) -> set[int]:
        return set(
            TikTokVideo.objects.filter(updated_at__gt=self.long_ago).values_list(
                "id_tiktok", flat=True
            )
        )

    def test_sets_the_priority_and_creates_missing_videos(self):
        self._video(11)
        self._make_old()
        self._write("https://www.tiktok.com/@a/video/11", "12")

        output = self._run("--priority", "5")

        self.assertEqual(self._manual(), {11: 5, 12: 5})
        self.assertEqual(self._moved(), {11, 12})
        self.assertEqual(
            TikTokVideo.objects.get(id_tiktok=12).added_by, DataOrigins.IMPORT
        )
        self.assertEqual(ScrapeTarget.objects.count(), 2)
        self.assertIn("Videos created: 1", output)
        self.assertIn("Priority set: 2", output)
        self.assertEqual(
            set(
                annotate_priority(TikTokVideo.objects.all()).values_list(
                    "priority", flat=True
                )
            ),
            {5},
        )

    def test_a_second_run_changes_nothing(self):
        self._write("11")
        self._run("--priority", "5")
        self._make_old()

        output = self._run("--priority", "5")

        self.assertEqual(self._moved(), set())
        self.assertIn("Priority set: 0", output)
        self.assertIn("Already had it: 1", output)

    def test_another_priority_replaces_the_old_one(self):
        self._video(11, manual_priority=5)
        self._make_old()
        self._write("11")

        self._run("--priority", "6")

        self.assertEqual(self._manual(), {11: 6})
        self.assertEqual(self._moved(), {11})

    def test_rejects_a_priority_below_1(self):
        self._write("11")

        with self.assertRaises(CommandError):
            self._run("--priority", "0")
        self.assertFalse(TikTokVideo.objects.exists())

    def test_a_derived_priority_can_be_set_by_hand(self):
        self._write("11")

        self._run("--priority", "1")

        self.assertEqual(self._manual(), {11: 1})

    def test_priority_or_remove_is_required(self):
        self._write("11")

        with self.assertRaises(CommandError):
            self._run()

    def test_remove_takes_the_priority_away(self):
        self._video(11, manual_priority=5)
        self._video(12)
        self._make_old()
        self._write("11", "12", "13")

        output = self._run("--remove")

        self.assertEqual(self._manual(), {11: None, 12: None})
        self.assertEqual(self._moved(), {11})
        self.assertEqual(ScrapeTarget.objects.count(), 0)
        self.assertIn("Manual priority removed: 1", output)
        self.assertIn("Had none: 1", output)
        self.assertIn("Not in the DB: 1", output)

    def test_dry_run_writes_nothing(self):
        self._video(11)
        self._write("11", "12")

        output = self._run("--priority", "5", "--dry-run")

        self.assertEqual(self._manual(), {11: None})
        self.assertIn("Dry run: nothing written.", output)

    def test_unparseable_values_are_counted(self):
        self._write("https://vm.tiktok.com/ZMabc/,a", ",b", "11,c", header="link,x")

        output = self._run("--priority", "5")

        self.assertIn("Rows read: 3", output)
        self.assertIn("Unparseable: 2", output)
        self.assertEqual(self._manual(), {11: 5})
