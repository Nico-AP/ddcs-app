from datetime import date, datetime, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from ddcs.metadata.dashboard.metrics import (
    get_classification_coverage,
    get_monitored_keyword_count,
    get_monitored_user_count,
    get_sync_coverage,
    get_video_counts_by_origin,
)
from ddcs.metadata.models import (
    DataOrigins,
    Keyword,
    SyncAttempt,
    TikTokUser,
    TikTokVideo,
    TikTokVideoClassification,
)
from ddcs.metadata.research_api.models import APIVideoInfos


class MetadataDashboardAccessTests(TestCase):
    def setUp(self):
        self.url = reverse("metadata:dashboard")

    @override_settings(DEBUG=False)
    def test_anonymous_gets_404(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)

    @override_settings(DEBUG=False)
    def test_non_superuser_gets_404(self):
        user = get_user_model().objects.create_user(username="regular", password="x")
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)

    @override_settings(DEBUG=False)
    def test_superuser_gets_200(self):
        user = get_user_model().objects.create_superuser(
            username="admin", password="x", email="admin@example.com"
        )
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("origin_counts", response.context)
        self.assertIn("keyword_coverage_plot", response.context)
        self.assertIn("user_coverage_plot", response.context)
        self.assertIn("classification_coverage_plot", response.context)


class GetVideoCountsByOriginTests(TestCase):
    def test_splits_by_api_info_presence(self):
        v1 = TikTokVideo.objects.create(id_tiktok=1, added_by=DataOrigins.RESEARCH_API)
        TikTokVideo.objects.create(id_tiktok=2, added_by=DataOrigins.RESEARCH_API)
        TikTokVideo.objects.create(id_tiktok=3, added_by=DataOrigins.DONATION)
        APIVideoInfos.objects.create(video=v1)

        counts = {row["added_by"]: row for row in get_video_counts_by_origin()}

        self.assertEqual(counts[DataOrigins.RESEARCH_API]["total"], 2)
        self.assertEqual(counts[DataOrigins.RESEARCH_API]["with_api_info"], 1)
        self.assertEqual(counts[DataOrigins.RESEARCH_API]["without_api_info"], 1)
        self.assertEqual(counts[DataOrigins.DONATION]["total"], 1)
        self.assertEqual(counts[DataOrigins.DONATION]["with_api_info"], 0)

    def test_does_not_double_count_videos_with_multiple_api_info_rows(self):
        video = TikTokVideo.objects.create(
            id_tiktok=1, added_by=DataOrigins.RESEARCH_API
        )
        APIVideoInfos.objects.create(video=video)
        APIVideoInfos.objects.create(video=video)

        counts = {row["added_by"]: row for row in get_video_counts_by_origin()}

        self.assertEqual(counts[DataOrigins.RESEARCH_API]["total"], 1)
        self.assertEqual(counts[DataOrigins.RESEARCH_API]["with_api_info"], 1)


class GetSyncCoverageTests(TestCase):
    def test_fills_missing_days_with_zero_and_counts_distinct_items(self):
        keyword = Keyword.objects.create(name="test", added_by=DataOrigins.IMPORT)
        today = timezone.localdate()
        SyncAttempt.objects.create(
            keyword=keyword, target_date=today, status=SyncAttempt.Status.SUCCESS
        )
        SyncAttempt.objects.create(
            keyword=keyword, target_date=today, status=SyncAttempt.Status.RATE_LIMITED
        )

        coverage = get_sync_coverage("keyword", today - timedelta(days=1), today)

        by_date = {day["date"]: day for day in coverage}
        self.assertEqual(by_date[today]["attempted"], 1)
        self.assertEqual(by_date[today]["succeeded"], 1)
        self.assertEqual(by_date[today - timedelta(days=1)]["attempted"], 0)
        self.assertEqual(by_date[today - timedelta(days=1)]["succeeded"], 0)

    def test_monitored_counts_only_include_active_flag(self):
        Keyword.objects.create(name="on", added_by=DataOrigins.IMPORT, monitor_api=True)
        Keyword.objects.create(
            name="off", added_by=DataOrigins.IMPORT, monitor_api=False
        )
        TikTokUser.objects.create(
            name="on-user", added_by=DataOrigins.IMPORT, monitor_api=True
        )

        self.assertEqual(get_monitored_keyword_count(), 1)
        self.assertEqual(get_monitored_user_count(), 1)


def _aware(day: date) -> datetime:
    return timezone.make_aware(datetime.combine(day, datetime.min.time()))


class GetClassificationCoverageTests(TestCase):
    def test_counts_classified_against_total_with_api_info(self):
        today = timezone.localdate()
        v1 = TikTokVideo.objects.create(id_tiktok=1, added_by=DataOrigins.RESEARCH_API)
        v2 = TikTokVideo.objects.create(id_tiktok=2, added_by=DataOrigins.RESEARCH_API)
        APIVideoInfos.objects.create(video=v1, create_time=_aware(today))
        APIVideoInfos.objects.create(video=v2, create_time=_aware(today))
        TikTokVideoClassification.objects.create(video=v1)

        coverage = get_classification_coverage(today, today)

        self.assertEqual(coverage[0]["total"], 2)
        self.assertEqual(coverage[0]["classified"], 1)

    def test_uses_latest_api_info_snapshot_date(self):
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        video = TikTokVideo.objects.create(
            id_tiktok=1, added_by=DataOrigins.RESEARCH_API
        )
        older = APIVideoInfos.objects.create(video=video, create_time=_aware(yesterday))
        older.created_at = _aware(yesterday)
        older.save(update_fields=["created_at"])
        APIVideoInfos.objects.create(video=video, create_time=_aware(today))

        coverage = {
            day["date"]: day for day in get_classification_coverage(yesterday, today)
        }

        self.assertEqual(coverage[today]["total"], 1)
        self.assertEqual(coverage[yesterday]["total"], 0)

    def test_excludes_video_whose_latest_snapshot_is_outside_the_range(self):
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        video = TikTokVideo.objects.create(
            id_tiktok=1, added_by=DataOrigins.RESEARCH_API
        )
        older = APIVideoInfos.objects.create(video=video, create_time=_aware(yesterday))
        older.created_at = _aware(yesterday)
        older.save(update_fields=["created_at"])
        APIVideoInfos.objects.create(video=video, create_time=_aware(today))

        coverage = get_classification_coverage(yesterday, yesterday)

        self.assertEqual(coverage[0]["total"], 0)

    def test_includes_last_moment_of_end_date_and_excludes_next_midnight(self):
        today = timezone.localdate()
        v1 = TikTokVideo.objects.create(id_tiktok=1, added_by=DataOrigins.RESEARCH_API)
        v2 = TikTokVideo.objects.create(id_tiktok=2, added_by=DataOrigins.RESEARCH_API)
        APIVideoInfos.objects.create(
            video=v1,
            create_time=_aware(today + timedelta(days=1)) - timedelta(seconds=1),
        )
        APIVideoInfos.objects.create(
            video=v2, create_time=_aware(today + timedelta(days=1))
        )

        coverage = get_classification_coverage(today, today)

        self.assertEqual(coverage[0]["total"], 1)
