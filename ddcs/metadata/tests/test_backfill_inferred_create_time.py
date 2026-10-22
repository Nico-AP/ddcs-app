from datetime import UTC, datetime
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase

from ddcs.metadata.models import DataOrigins, TikTokVideo
from ddcs.metadata.utils import infer_publication_date_from_id


class BackfillInferredCreateTimeTests(TestCase):
    def setUp(self):
        self.stored = datetime(2020, 1, 1, tzinfo=UTC)
        for id_tiktok in range(1, 8):
            TikTokVideo.objects.create(
                id_tiktok=id_tiktok, added_by=DataOrigins.DONATION
            )
        TikTokVideo.objects.create(
            id_tiktok=100,
            added_by=DataOrigins.RESEARCH_API,
            inferred_create_time=self.stored,
        )

    def _run(self, *args: str) -> str:
        out = StringIO()
        call_command("backfill_inferred_create_time", *args, stdout=out)
        return out.getvalue()

    def test_fills_in_missing_values_in_chunks(self):
        updated_at = dict(TikTokVideo.objects.values_list("pk", "updated_at"))

        output = self._run("--chunk-size", "3")

        self.assertIn("Videos updated: 7", output)
        for video in TikTokVideo.objects.exclude(id_tiktok=100):
            with self.subTest(id_tiktok=video.id_tiktok):
                self.assertEqual(
                    video.inferred_create_time,
                    infer_publication_date_from_id(video.id_tiktok),
                )
                # Not reported as changed by the prioritised video API.
                self.assertEqual(video.updated_at, updated_at[video.pk])

    def test_leaves_existing_values_alone(self):
        self._run()

        self.assertEqual(
            TikTokVideo.objects.get(id_tiktok=100).inferred_create_time, self.stored
        )

    def test_second_run_updates_nothing(self):
        self._run()

        self.assertIn("Videos updated: 0", self._run())

    def test_dry_run_only_counts(self):
        output = self._run("--dry-run")

        self.assertIn("Videos without inferred_create_time: 7", output)
        self.assertEqual(
            TikTokVideo.objects.filter(inferred_create_time__isnull=True).count(), 7
        )

    def test_chunk_size_must_be_positive(self):
        with self.assertRaises(CommandError):
            self._run("--chunk-size", "0")
