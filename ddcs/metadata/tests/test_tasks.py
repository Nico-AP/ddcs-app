from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import patch

from celery.exceptions import Retry, SoftTimeLimitExceeded
from django.test import TestCase, override_settings

from ddcs.metadata.models import DataOrigins, TikTokVideo
from ddcs.metadata.research_api.models import APIVideoInfos
from ddcs.metadata.tasks import (
    backfill_tiktok_video_classifications,
    notify_backfill_chain_broken,
    sync_tiktok_video_classifications,
)


def _create_api_info(video: TikTokVideo, created_at: datetime) -> APIVideoInfos:
    info = APIVideoInfos.objects.create(video=video)
    APIVideoInfos.objects.filter(pk=info.pk).update(created_at=created_at)
    return info


@override_settings(ZUSE_API_TOKEN="test-token", ZUSE_API_URL="https://zuse.example.com")
class SyncTikTokVideoClassificationsTests(TestCase):
    def setUp(self):
        redis_patcher = patch("ddcs.metadata.tasks.Redis")
        self.mock_redis = redis_patcher.start()
        self.addCleanup(redis_patcher.stop)
        self.lock = self.mock_redis.from_url.return_value.lock.return_value
        self.lock.acquire.return_value = True

        self.target_date = "2026-09-09"
        self.matching_datetime = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
        self.other_datetime = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)

    def _create_video(self, id_tiktok: int) -> TikTokVideo:
        return TikTokVideo.objects.create(
            id_tiktok=id_tiktok, added_by=DataOrigins.DONATION
        )

    def test_syncs_videos_with_api_info_on_target_date(self):
        video = self._create_video(1)
        _create_api_info(video, self.matching_datetime)

        with patch("ddcs.metadata.tasks.ZuseAPIClient.sync_videos") as mock_sync:
            sync_tiktok_video_classifications(self.target_date)

        mock_sync.assert_called_once_with([video.id_tiktok])

    def test_ignores_videos_without_api_info(self):
        self._create_video(1)

        with patch("ddcs.metadata.tasks.ZuseAPIClient.sync_videos") as mock_sync:
            sync_tiktok_video_classifications(self.target_date)

        mock_sync.assert_not_called()

    def test_ignores_api_info_from_other_dates(self):
        video = self._create_video(1)
        _create_api_info(video, self.other_datetime)

        with patch("ddcs.metadata.tasks.ZuseAPIClient.sync_videos") as mock_sync:
            sync_tiktok_video_classifications(self.target_date)

        mock_sync.assert_not_called()

    def test_does_not_duplicate_video_with_multiple_api_infos_same_date(self):
        video = self._create_video(1)
        _create_api_info(video, self.matching_datetime)
        _create_api_info(video, self.matching_datetime.replace(hour=18))

        with patch("ddcs.metadata.tasks.ZuseAPIClient.sync_videos") as mock_sync:
            sync_tiktok_video_classifications(self.target_date)

        mock_sync.assert_called_once_with([video.id_tiktok])

    def test_processes_videos_in_batches(self):
        videos = [self._create_video(i) for i in range(3)]
        for video in videos:
            _create_api_info(video, self.matching_datetime)

        with (
            patch("ddcs.metadata.tasks.ZuseAPIClient.sync_videos") as mock_sync,
        ):
            sync_tiktok_video_classifications(self.target_date, batch_size=2)

        self.assertEqual(mock_sync.call_count, 2)
        self.assertEqual(len(mock_sync.call_args_list[0].args[0]), 2)
        self.assertEqual(len(mock_sync.call_args_list[1].args[0]), 1)

    def test_max_videos_caps_the_number_synced(self):
        videos = [self._create_video(i) for i in range(3)]
        for video in videos:
            _create_api_info(video, self.matching_datetime)

        with patch("ddcs.metadata.tasks.ZuseAPIClient.sync_videos") as mock_sync:
            sync_tiktok_video_classifications(self.target_date, max_videos=2)

        mock_sync.assert_called_once()
        self.assertEqual(len(mock_sync.call_args.args[0]), 2)

    def test_completes_without_retry_when_within_time_budget(self):
        video = self._create_video(1)
        _create_api_info(video, self.matching_datetime)

        with (
            patch("ddcs.metadata.tasks.ZuseAPIClient.sync_videos"),
            patch.object(sync_tiktok_video_classifications, "retry") as mock_retry,
        ):
            sync_tiktok_video_classifications(self.target_date)

        mock_retry.assert_not_called()

    def test_respawns_when_approaching_soft_time_limit(self):
        videos = [self._create_video(i) for i in range(4)]
        for video in videos:
            _create_api_info(video, self.matching_datetime)

        # Chunk size 2 -> two chunks of 2 videos each. Budget is exceeded
        # right after the first chunk, so the task should respawn instead
        # of processing the second chunk.
        with (
            patch("ddcs.metadata.tasks.ZuseAPIClient.sync_videos") as mock_sync,
            patch("ddcs.metadata.tasks.time.monotonic", side_effect=[0, 10_000]),
            patch.object(
                sync_tiktok_video_classifications, "retry", side_effect=Retry()
            ) as mock_retry,
            self.assertRaises(Retry),
        ):
            sync_tiktok_video_classifications(self.target_date, batch_size=2)

        mock_sync.assert_called_once()
        mock_retry.assert_called_once_with(
            kwargs={"target_date": self.target_date}, countdown=5
        )

    def test_respawns_with_remaining_max_videos_on_time_budget(self):
        videos = [self._create_video(i) for i in range(4)]
        for video in videos:
            _create_api_info(video, self.matching_datetime)

        with (
            patch("ddcs.metadata.tasks.ZuseAPIClient.sync_videos"),
            patch("ddcs.metadata.tasks.time.monotonic", side_effect=[0, 10_000]),
            patch.object(
                sync_tiktok_video_classifications, "retry", side_effect=Retry()
            ) as mock_retry,
            self.assertRaises(Retry),
        ):
            sync_tiktok_video_classifications(
                self.target_date, max_videos=3, batch_size=2
            )

        mock_retry.assert_called_once_with(
            kwargs={"target_date": self.target_date, "max_videos": 1},
            countdown=5,
        )

    def test_respawns_on_soft_time_limit_exceeded_mid_chunk(self):
        videos = [self._create_video(i) for i in range(4)]
        for video in videos:
            _create_api_info(video, self.matching_datetime)

        with (
            patch(
                "ddcs.metadata.tasks.ZuseAPIClient.sync_videos",
                side_effect=SoftTimeLimitExceeded(),
            ),
            patch("ddcs.metadata.tasks.recover_db_connection") as mock_recover,
            patch.object(
                sync_tiktok_video_classifications, "retry", side_effect=Retry()
            ) as mock_retry,
            self.assertRaises(Retry),
        ):
            sync_tiktok_video_classifications(
                self.target_date, max_videos=3, batch_size=2
            )

        mock_recover.assert_called_once()
        mock_retry.assert_called_once_with(
            kwargs={"target_date": self.target_date, "max_videos": 3},
            countdown=5,
        )

    def test_retries_without_syncing_when_lock_is_held(self):
        video = self._create_video(1)
        _create_api_info(video, self.matching_datetime)
        self.lock.acquire.return_value = False

        with (
            patch("ddcs.metadata.tasks.ZuseAPIClient.sync_videos") as mock_sync,
            patch.object(
                sync_tiktok_video_classifications, "retry", side_effect=Retry()
            ) as mock_retry,
            self.assertRaises(Retry),
        ):
            sync_tiktok_video_classifications(self.target_date)

        mock_sync.assert_not_called()
        mock_retry.assert_called_once_with(countdown=60)
        self.lock.release.assert_not_called()

    def test_releases_lock_after_sync(self):
        video = self._create_video(1)
        _create_api_info(video, self.matching_datetime)

        with patch("ddcs.metadata.tasks.ZuseAPIClient.sync_videos"):
            sync_tiktok_video_classifications(self.target_date)

        self.lock.release.assert_called_once()

    def test_releases_lock_when_sync_fails(self):
        video = self._create_video(1)
        _create_api_info(video, self.matching_datetime)

        with (
            patch(
                "ddcs.metadata.tasks.ZuseAPIClient.sync_videos",
                side_effect=RuntimeError("boom"),
            ),
            self.assertRaises(RuntimeError),
        ):
            sync_tiktok_video_classifications(self.target_date)

        self.lock.release.assert_called_once()


class BackfillTikTokVideoClassificationsTests(TestCase):
    def setUp(self):
        chain_patcher = patch("ddcs.metadata.tasks.chain")
        self.mock_chain = chain_patcher.start()
        self.addCleanup(chain_patcher.stop)

    def _chained_signatures(self):
        return list(self.mock_chain.call_args.args)

    def _chained_dates(self) -> list[str]:
        return [sig.kwargs["target_date"] for sig in self._chained_signatures()]

    def test_chains_inclusive_range_newest_first(self):
        count = backfill_tiktok_video_classifications(
            start_date="2026-09-10", end_date="2026-09-08"
        )

        self.assertEqual(count, 3)
        self.assertEqual(
            self._chained_dates(), ["2026-09-10", "2026-09-09", "2026-09-08"]
        )
        self.mock_chain.return_value.on_error.return_value.apply_async.assert_called_once_with()

    def test_chained_signatures_are_immutable_sync_tasks(self):
        backfill_tiktok_video_classifications(
            start_date="2026-09-10", end_date="2026-09-09"
        )

        for sig in self._chained_signatures():
            self.assertEqual(sig.task, sync_tiktok_video_classifications.name)
            self.assertTrue(sig.immutable)

    def test_defaults_run_from_today_to_july_first(self):
        today = date(2026, 9, 18)
        with patch("ddcs.metadata.tasks.timezone.localdate", return_value=today):
            count = backfill_tiktok_video_classifications()

        dates = self._chained_dates()
        self.assertEqual(count, (today - date(2026, 7, 1)).days + 1)
        self.assertEqual(dates[0], "2026-09-18")
        self.assertEqual(dates[-1], "2026-07-01")
        self.assertEqual(len(dates), len(set(dates)))

    def test_same_start_and_end_chains_single_task(self):
        count = backfill_tiktok_video_classifications(
            start_date="2026-09-09", end_date="2026-09-09"
        )

        self.assertEqual(count, 1)
        self.assertEqual(self._chained_dates(), ["2026-09-09"])

    def test_raises_when_start_is_before_end(self):
        with self.assertRaises(ValueError):
            backfill_tiktok_video_classifications(
                start_date="2026-09-01", end_date="2026-09-09"
            )

        self.mock_chain.assert_not_called()

    def test_forwards_batch_size_and_max_videos(self):
        backfill_tiktok_video_classifications(
            start_date="2026-09-09",
            end_date="2026-09-09",
            batch_size=25,
            max_videos=50,
        )

        (sig,) = self._chained_signatures()
        self.assertEqual(
            sig.kwargs,
            {"target_date": "2026-09-09", "batch_size": 25, "max_videos": 50},
        )

    def test_chain_reports_failures_to_the_error_callback(self):
        backfill_tiktok_video_classifications(
            start_date="2026-09-10", end_date="2026-09-08"
        )

        (errback,), _ = self.mock_chain.return_value.on_error.call_args
        self.assertEqual(errback.task, notify_backfill_chain_broken.name)
        self.assertEqual(errback.kwargs, {"end_date": "2026-09-08"})


class NotifyBackfillChainBrokenTests(TestCase):
    def test_logs_error_naming_failed_and_skipped_dates(self):
        # request.chain lists the remaining tasks with the next one last.
        request = SimpleNamespace(
            kwargs={"target_date": "2026-09-08"},
            chain=[
                {"kwargs": {"target_date": "2026-09-06"}},
                {"kwargs": {"target_date": "2026-09-07"}},
            ],
        )

        with self.assertLogs("ddcs.metadata.tasks", level="ERROR") as logs:
            notify_backfill_chain_broken(
                request, RuntimeError("zuse down"), "tb", end_date="2026-09-06"
            )

        (message,) = logs.output
        self.assertIn("broke at 2026-09-08", message)
        self.assertIn("zuse down", message)
        self.assertIn("2 later date(s)", message)
        self.assertIn("2026-09-07, 2026-09-06", message)
        self.assertIn("start_date='2026-09-08', end_date='2026-09-06'", message)

    def test_handles_failure_of_last_date(self):
        request = SimpleNamespace(kwargs={"target_date": "2026-09-06"}, chain=None)

        with self.assertLogs("ddcs.metadata.tasks", level="ERROR") as logs:
            notify_backfill_chain_broken(
                request, RuntimeError("boom"), "tb", end_date="2026-09-06"
            )

        self.assertIn("0 later date(s)", logs.output[0])
        self.assertIn("none", logs.output[0])
