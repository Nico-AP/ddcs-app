import tempfile
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase

from ddcs.metadata.donations.models import DonationVideoInfos
from ddcs.metadata.management.commands.import_video_links import _video_id
from ddcs.metadata.models import DataOrigins, TikTokVideo
from ddcs.metadata.priority import VideoPriority, annotate_priority
from ddcs.metadata.research_api.models import APIVideoInfos
from ddcs.metadata.scraper.models import ScrapeTarget
from ddcs.metadata.utils import infer_publication_date_from_id, new_video, video_pks

Status = ScrapeTarget.Status


class VideoIdTests(TestCase):
    def test_parses_links_and_bare_ids(self):
        cases = {
            "https://www.tiktok.com/@user/video/7100000000000000001": (
                7100000000000000001
            ),
            "https://www.tiktok.com/@user/video/12345/": 12345,
            "https://www.tiktok.com/@user/video/12345?_r=1&u_code=abc": 12345,
            "https://www.tiktok.com/@user/photo/99#foo": 99,
            " 42 ": 42,
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(_video_id(value), expected)

    def test_rejects_values_without_a_video_id(self):
        for value in (
            "",
            "https://vm.tiktok.com/ZMabc123/",
            "https://www.tiktok.com/@user",
            "https://www.tiktok.com/@user/123",
            "not a link",
        ):
            with self.subTest(value=value):
                self.assertIsNone(_video_id(value))


class NewVideoTests(TestCase):
    def test_sets_the_inferred_create_time(self):
        id_tiktok = 7100000000000000001

        video = new_video(id_tiktok, DataOrigins.DATAPODS)

        self.assertIsNone(video.pk)
        self.assertEqual(video.added_by, DataOrigins.DATAPODS)
        self.assertEqual(
            video.inferred_create_time, infer_publication_date_from_id(id_tiktok)
        )


class VideoPksTests(TestCase):
    def test_created_rows_get_the_given_origin(self):
        TikTokVideo.objects.create(id_tiktok=1, added_by=DataOrigins.DONATION)

        video_pks([1, 2], added_by=DataOrigins.DATAPODS)

        self.assertEqual(
            dict(TikTokVideo.objects.values_list("id_tiktok", "added_by")),
            {1: DataOrigins.DONATION, 2: DataOrigins.DATAPODS},
        )
        self.assertEqual(
            TikTokVideo.objects.get(id_tiktok=2).inferred_create_time,
            infer_publication_date_from_id(2),
        )


class ImportVideoLinksTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "videos.csv"

    def _write(self, *rows: str, header: str = "link,other") -> None:
        self.path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")

    def _run(self, *args: str) -> str:
        out = StringIO()
        call_command(
            "import_video_links",
            str(self.path),
            "--origin",
            "DATAPODS",
            *args,
            stdout=out,
        )
        return out.getvalue()

    def test_imports_videos_and_queues_them_after_donations(self):
        self._write(
            "https://www.tiktok.com/@a/video/11?lang=de,x",
            "https://www.tiktok.com/@b/photo/12/,y",
            "13,z",
        )

        output = self._run()

        self.assertIn("Scrape targets created: 3", output)
        self.assertEqual(
            set(TikTokVideo.objects.values_list("id_tiktok", "added_by")),
            {(i, DataOrigins.DATAPODS) for i in (11, 12, 13)},
        )
        self.assertEqual(
            set(
                ScrapeTarget.objects.values_list(
                    "status", "occurrence_count", "last_watched_at"
                )
            ),
            {(Status.PENDING, 0, None)},
        )

    def test_unparseable_and_duplicate_rows_are_not_imported(self):
        self._write(
            "https://www.tiktok.com/@a/video/11,",
            "https://www.tiktok.com/@a/video/11?x=1,",
            "https://vm.tiktok.com/ZMabc/,",
            ",",
        )

        output = self._run()

        self.assertIn("Rows read: 4", output)
        self.assertIn("Unparseable: 2", output)
        self.assertIn("'https://vm.tiktok.com/ZMabc/'", output)
        self.assertEqual(ScrapeTarget.objects.count(), 1)

    def test_existing_videos_and_targets_are_left_alone(self):
        donated = TikTokVideo.objects.create(
            id_tiktok=11, added_by=DataOrigins.DONATION
        )
        ScrapeTarget.objects.create(
            video=donated, status=Status.SUCCESS, attempts=1, occurrence_count=4
        )
        covered = TikTokVideo.objects.create(
            id_tiktok=12, added_by=DataOrigins.RESEARCH_API
        )
        APIVideoInfos.objects.create(video=covered)
        self._write("11,", "12,", "13,")

        output = self._run()

        self.assertIn("Videos created: 1", output)
        self.assertIn("Already queued: 1", output)
        self.assertIn("Skipped, Research API has the video: 1", output)
        donated.refresh_from_db()
        self.assertEqual(donated.added_by, DataOrigins.DONATION)
        target = ScrapeTarget.objects.get(video=donated)
        self.assertEqual((target.status, target.occurrence_count), (Status.SUCCESS, 4))
        self.assertFalse(ScrapeTarget.objects.filter(video=covered).exists())

    def test_chunks_and_repeated_runs(self):
        self._write(*(f"{i}," for i in range(1, 8)))

        self._run("--chunk-size", "3")
        output = self._run("--chunk-size", "3")

        self.assertIn("Videos created: 0", output)
        self.assertIn("Scrape targets created: 0", output)
        self.assertIn("Already queued: 7", output)
        self.assertEqual(ScrapeTarget.objects.count(), 7)
        self.assertEqual(
            set(ScrapeTarget.objects.values_list("occurrence_count", flat=True)), {0}
        )

    def test_dry_run_writes_nothing(self):
        self._write("11,", "12,")

        output = self._run("--dry-run")

        self.assertIn("Video IDs: 2", output)
        self.assertFalse(TikTokVideo.objects.exists())
        self.assertFalse(ScrapeTarget.objects.exists())

    def test_other_column_name(self):
        self._write("x,11", header="other,url")

        self._run("--column", "url")

        self.assertEqual(ScrapeTarget.objects.get().video.id_tiktok, 11)

    def test_missing_column_is_an_error(self):
        self._write("11,", header="url,other")

        with self.assertRaisesMessage(CommandError, "Column 'link' not found"):
            self._run()

    def test_origin_is_required(self):
        self._write("11,")

        with self.assertRaises(CommandError):
            call_command("import_video_links", str(self.path), stdout=StringIO())

    def test_existing_videos_are_marked_and_rise_in_priority(self):
        # Donated only outside the window: priority 1 before the import.
        video = TikTokVideo.objects.create(id_tiktok=11, added_by=DataOrigins.DONATION)
        DonationVideoInfos.objects.create(
            video=video,
            last_interaction_at=datetime(2026, 10, 5, tzinfo=UTC),
            last_interaction_in_window_at=None,
        )
        before = TikTokVideo.objects.get(pk=video.pk).updated_at
        self._write("11,", "12,")

        output = self._run()

        self.assertIn("Marked as Datapods: 2", output)
        video.refresh_from_db()
        self.assertTrue(video.in_datapods)
        self.assertEqual(video.added_by, DataOrigins.DONATION)
        self.assertGreater(video.updated_at, before)
        self.assertEqual(
            annotate_priority(TikTokVideo.objects.filter(pk=video.pk)).get().priority,
            VideoPriority.DONATED_IN_WINDOW,
        )

    def test_repeated_run_marks_nothing_more(self):
        self._write("11,")
        self._run()
        updated_at = TikTokVideo.objects.get().updated_at

        output = self._run()

        self.assertIn("Marked as Datapods: 0", output)
        self.assertEqual(TikTokVideo.objects.get().updated_at, updated_at)

    def test_other_origins_mark_nothing(self):
        self._write("11,")

        call_command(
            "import_video_links",
            str(self.path),
            "--origin",
            "IMPORT",
            stdout=StringIO(),
        )

        video = TikTokVideo.objects.get()
        self.assertEqual(video.added_by, DataOrigins.IMPORT)
        self.assertFalse(video.in_datapods)
