from datetime import UTC, datetime
from unittest.mock import patch

from django.test import TestCase, override_settings

from ddcs.metadata.models import DataOrigins, TikTokVideo
from ddcs.metadata.research_api.models import APIVideoInfos
from ddcs.metadata.tasks import sync_tiktok_video_classifications


def _create_api_info(video: TikTokVideo, created_at: datetime) -> APIVideoInfos:
    info = APIVideoInfos.objects.create(video=video)
    APIVideoInfos.objects.filter(pk=info.pk).update(created_at=created_at)
    return info


@override_settings(ZUSE_API_TOKEN="test-token", ZUSE_API_URL="https://zuse.example.com")
class SyncTikTokVideoClassificationsTests(TestCase):
    def setUp(self):
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
            patch("ddcs.metadata.tasks.ZuseAPIClient.BATCH_SIZE", 2),
            patch("ddcs.metadata.tasks.ZuseAPIClient.sync_videos") as mock_sync,
        ):
            sync_tiktok_video_classifications(self.target_date)

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
