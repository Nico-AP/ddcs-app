from datetime import date, datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from ddcs.metadata.dashboard.metrics import (
    get_classification_coverage,
    get_dashboard_snapshot,
    get_monitored_keyword_count,
    get_monitored_user_count,
    get_scraper_queue,
    get_suspicious_sync_days,
    get_sync_coverage,
    get_sync_video_counts,
    get_video_counts_by_origin,
    refresh_dashboard_snapshot,
)
from ddcs.metadata.models import (
    DataOrigins,
    Keyword,
    ResearchAPIQueryTracker,
    SyncAttempt,
    TikTokUser,
    TikTokVideo,
    TikTokVideoClassification,
)
from ddcs.metadata.research_api.models import APIVideoInfos
from ddcs.metadata.scraper.models import ScrapeTarget
from ddcs.metadata.scraper.service import (
    get_cooldown,
    record_last_run,
    register_abort,
)
from ddcs.metadata.tasks import (
    _DASHBOARD_REFRESH_PENDING_KEY,
    refresh_metadata_dashboard,
    request_dashboard_refresh,
)

_REQUEST_REFRESH = "ddcs.metadata.dashboard.views.request_dashboard_refresh"


class MetadataDashboardAccessTests(TestCase):
    def setUp(self):
        self.url = reverse("metadata:dashboard")
        cache.clear()
        self.addCleanup(cache.clear)
        refresh_dashboard_snapshot()

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


def _tracker(
    target_date: date,
    videos: int | None,
    *,
    task_name: str = "daily_sync_keywords",
    pages: int = 1,
) -> ResearchAPIQueryTracker:
    """A finished sync run for ``target_date``; ``videos=None`` = no result."""
    return ResearchAPIQueryTracker.objects.create(
        start_time=timezone.now(),
        query_function=task_name,
        query_parameters={"target_date": target_date.isoformat()},
        query_result=(
            None
            if videos is None
            else {"videos_retrieved": videos, "pages_retrieved": pages}
        ),
    )


class GetSyncVideoCountsTests(TestCase):
    def setUp(self):
        self.end = timezone.localdate() - timedelta(days=4)
        self.start = self.end - timedelta(days=2)

    def _by_date(self, target_field: str = "keyword") -> dict:
        counts = get_sync_video_counts(target_field, self.start, self.end)
        return {day["date"]: day for day in counts}

    def test_sums_runs_for_the_same_target_date(self):
        _tracker(self.end, 10, pages=2)
        _tracker(self.end, 5, pages=1)

        day = self._by_date()[self.end]

        self.assertEqual(day["videos"], 15)
        self.assertEqual(day["pages"], 3)

    def test_distinguishes_no_result_from_zero_videos(self):
        _tracker(self.end, 0)
        # A run that never reported a result (still running, or reaped).
        _tracker(self.end - timedelta(days=1), None)

        by_date = self._by_date()

        self.assertEqual(by_date[self.end]["videos"], 0)
        self.assertIsNone(by_date[self.end - timedelta(days=1)]["videos"])
        self.assertIsNone(by_date[self.start]["videos"])

    def test_only_counts_runs_of_the_requested_target(self):
        _tracker(self.end, 7, task_name="daily_sync_users")

        self.assertIsNone(self._by_date("keyword")[self.end]["videos"])
        self.assertEqual(self._by_date("user")[self.end]["videos"], 7)

    def test_ignores_target_dates_outside_the_range(self):
        _tracker(self.end + timedelta(days=1), 3)

        self.assertEqual(
            [day["videos"] for day in self._by_date().values()], [None, None, None]
        )

    def test_runs_a_single_query(self):
        _tracker(self.end, 1)
        _tracker(self.start, 2)

        with self.assertNumQueries(1):
            get_sync_video_counts("keyword", self.start, self.end)


class GetSuspiciousSyncDaysTests(TestCase):
    def test_lists_only_days_with_successes_and_zero_videos_newest_first(self):
        d1, d2, d3, d4 = (date(2026, 9, n) for n in (1, 2, 3, 4))
        coverage = [
            {"date": d1, "attempted": 5, "succeeded": 5},
            {"date": d2, "attempted": 5, "succeeded": 5},  # videos came back
            {"date": d3, "attempted": 5, "succeeded": 0},  # nothing succeeded
            {"date": d4, "attempted": 5, "succeeded": 4},
        ]
        video_counts = [
            {"date": d1, "videos": 0, "pages": 1},
            {"date": d2, "videos": 12, "pages": 1},
            {"date": d3, "videos": 0, "pages": 0},
            {"date": d4, "videos": 0, "pages": 2},
        ]

        self.assertEqual(
            get_suspicious_sync_days(coverage, video_counts),
            [
                {"date": d4, "succeeded": 4, "pages": 2},
                {"date": d1, "succeeded": 5, "pages": 1},
            ],
        )

    def test_skips_days_without_a_reported_result(self):
        day = date(2026, 9, 1)

        self.assertEqual(
            get_suspicious_sync_days(
                [{"date": day, "attempted": 5, "succeeded": 5}],
                [{"date": day, "videos": None, "pages": None}],
            ),
            [],
        )


class MetadataDashboardSyncVideoCountsViewTests(TestCase):
    def setUp(self):
        self.url = reverse("metadata:dashboard")
        self.client.force_login(
            get_user_model().objects.create_superuser(
                username="admin", password="x", email="admin@example.com"
            )
        )
        cache.clear()
        self.addCleanup(cache.clear)
        refresh_dashboard_snapshot()

    def test_flags_day_with_successful_sync_but_no_videos(self):
        keyword = Keyword.objects.create(name="test", added_by=DataOrigins.IMPORT)
        day = timezone.localdate() - timedelta(days=4)
        SyncAttempt.objects.create(
            keyword=keyword, target_date=day, status=SyncAttempt.Status.SUCCESS
        )
        _tracker(day, 0)

        response = self.client.get(self.url)

        self.assertEqual(
            response.context["keyword_suspicious_days"],
            [{"date": day, "succeeded": 1, "pages": 1}],
        )
        self.assertEqual(response.context["user_suspicious_days"], [])
        self.assertContains(response, "Synced successfully, but no videos returned")

    def test_query_count_does_not_grow_with_the_number_of_runs(self):
        day = timezone.localdate() - timedelta(days=4)
        _tracker(day, 1)
        with CaptureQueriesContext(connection) as baseline:
            self.client.get(self.url)

        for offset in range(10):
            _tracker(day - timedelta(days=offset), offset)
            _tracker(day - timedelta(days=offset), 3, task_name="daily_sync_users")

        with self.assertNumQueries(len(baseline.captured_queries)):
            self.client.get(self.url)


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

    def test_counts_video_with_multiple_snapshots_on_a_day_once(self):
        today = timezone.localdate()
        video = TikTokVideo.objects.create(
            id_tiktok=1, added_by=DataOrigins.RESEARCH_API
        )
        APIVideoInfos.objects.create(video=video, create_time=_aware(today))
        APIVideoInfos.objects.create(
            video=video, create_time=_aware(today) + timedelta(hours=1)
        )
        TikTokVideoClassification.objects.create(video=video)

        coverage = get_classification_coverage(today, today)

        self.assertEqual(coverage[0]["total"], 1)
        self.assertEqual(coverage[0]["classified"], 1)

    def test_excludes_videos_published_outside_the_range(self):
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        video = TikTokVideo.objects.create(
            id_tiktok=1, added_by=DataOrigins.RESEARCH_API
        )
        APIVideoInfos.objects.create(video=video, create_time=_aware(today))

        coverage = get_classification_coverage(yesterday, yesterday)

        self.assertEqual(coverage[0]["total"], 0)

    def test_ignores_snapshots_without_publish_date(self):
        today = timezone.localdate()
        video = TikTokVideo.objects.create(
            id_tiktok=1, added_by=DataOrigins.RESEARCH_API
        )
        APIVideoInfos.objects.create(video=video, create_time=None)

        coverage = get_classification_coverage(today, today)

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


class DashboardSnapshotTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_snapshot_is_none_until_refreshed(self):
        self.assertIsNone(get_dashboard_snapshot())

    def test_refresh_caches_origin_counts_and_whole_history(self):
        today = timezone.localdate()
        long_ago = today - timedelta(days=400)
        v1 = TikTokVideo.objects.create(id_tiktok=1, added_by=DataOrigins.RESEARCH_API)
        v2 = TikTokVideo.objects.create(id_tiktok=2, added_by=DataOrigins.RESEARCH_API)
        APIVideoInfos.objects.create(video=v1, create_time=_aware(today))
        APIVideoInfos.objects.create(video=v2, create_time=_aware(long_ago))
        TikTokVideoClassification.objects.create(video=v2)

        refresh_dashboard_snapshot()
        snapshot = get_dashboard_snapshot()

        self.assertEqual(snapshot["origin_counts"][0]["with_api_info"], 2)
        self.assertEqual(
            snapshot["classification_by_date"],
            {
                today.isoformat(): {"total": 1, "classified": 0},
                long_ago.isoformat(): {"total": 1, "classified": 1},
            },
        )

    def test_task_refreshes_snapshot_and_clears_pending_flag(self):
        cache.set(_DASHBOARD_REFRESH_PENDING_KEY, True)

        refresh_metadata_dashboard()

        self.assertIsNotNone(get_dashboard_snapshot())
        self.assertIsNone(cache.get(_DASHBOARD_REFRESH_PENDING_KEY))

    def test_request_refresh_queues_only_once_while_pending(self):
        with patch("ddcs.metadata.tasks.refresh_metadata_dashboard.delay") as delay:
            self.assertTrue(request_dashboard_refresh())
            self.assertFalse(request_dashboard_refresh())

        delay.assert_called_once_with()


class MetadataDashboardSnapshotViewTests(TestCase):
    def setUp(self):
        self.url = reverse("metadata:dashboard")
        self.client.force_login(
            get_user_model().objects.create_superuser(
                username="admin", password="x", email="admin@example.com"
            )
        )
        cache.clear()
        self.addCleanup(cache.clear)

    def test_cache_miss_queues_refresh_and_still_renders(self):
        with (
            patch(_REQUEST_REFRESH) as request_refresh,
            patch(
                "ddcs.metadata.dashboard.metrics.get_video_counts_by_origin"
            ) as compute,
        ):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        request_refresh.assert_called_once_with()
        compute.assert_not_called()
        self.assertIsNone(response.context["snapshot_computed_at"])
        self.assertEqual(response.context["origin_counts"], [])
        self.assertContains(response, "being computed")

    def test_cache_hit_serves_snapshot_without_queueing(self):
        video = TikTokVideo.objects.create(
            id_tiktok=1, added_by=DataOrigins.RESEARCH_API
        )
        APIVideoInfos.objects.create(
            video=video, create_time=_aware(timezone.localdate())
        )
        snapshot = refresh_dashboard_snapshot()
        # Added after the snapshot: must not show up until the next refresh.
        TikTokVideo.objects.create(id_tiktok=2, added_by=DataOrigins.RESEARCH_API)

        with patch(_REQUEST_REFRESH) as request_refresh:
            response = self.client.get(self.url)

        request_refresh.assert_not_called()
        self.assertEqual(
            response.context["snapshot_computed_at"], snapshot["computed_at"]
        )
        self.assertEqual(response.context["origin_counts"][0]["total"], 1)
        self.assertIsNotNone(response.context["classification_coverage_plot"]["html"])

    def test_post_queues_refresh_and_redirects_to_same_range(self):
        url = f"{self.url}?start=2026-08-01&end=2026-08-31"

        with patch(_REQUEST_REFRESH) as request_refresh:
            response = self.client.post(url)

        request_refresh.assert_called_once_with()
        self.assertRedirects(response, url, fetch_redirect_response=False)


class GetScraperQueueTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_empty_queue_lists_every_status_with_zero(self):
        queue = get_scraper_queue()

        self.assertEqual(queue["total"], 0)
        self.assertIsNone(queue["last_success_at"])
        self.assertIsNone(queue["last_run"])
        self.assertEqual(
            [row["status"] for row in queue["by_status"]], ScrapeTarget.Status.values
        )
        self.assertEqual({row["count"] for row in queue["by_status"]}, {0})

    def test_last_run_is_reported_and_rendered(self):
        record_last_run(
            {
                "scraped": 40,
                "unavailable": 3,
                "failed": 2,
                "blocked": 1,
                "covered_by_api": 0,
                "captions_fetched": 25,
                "captions_failed": 4,
                "aborted": False,
                "seconds": 61.5,
                "videos_per_minute": 44.9,
            }
        )

        self.assertEqual(get_scraper_queue()["last_run"]["videos_per_minute"], 44.9)

        user = get_user_model().objects.create_superuser(
            username="admin", password="x", email="admin@example.com"
        )
        self.client.force_login(user)
        with patch(_REQUEST_REFRESH):
            response = self.client.get(reverse("metadata:dashboard"))

        self.assertContains(response, "44.9 videos/min")
        self.assertContains(response, "captions failed 4")
        self.assertNotContains(response, "aborted:")
        self.assertNotContains(response, "Scraping is paused")
        self.assertNotContains(response, "Resume scraping now")

    def test_counts_targets_per_status_and_reports_last_success(self):
        scraped_at = timezone.now()
        for id_tiktok, status, attempted_at in (
            (1, ScrapeTarget.Status.PENDING, None),
            (2, ScrapeTarget.Status.PENDING, None),
            (3, ScrapeTarget.Status.SUCCESS, scraped_at),
            (4, ScrapeTarget.Status.FAILED, scraped_at + timedelta(hours=1)),
        ):
            video = TikTokVideo.objects.create(
                id_tiktok=id_tiktok, added_by=DataOrigins.DONATION
            )
            ScrapeTarget.objects.create(
                video=video,
                status=status,
                last_attempted_at=attempted_at,
            )

        queue = get_scraper_queue()

        counts = {row["status"]: row["count"] for row in queue["by_status"]}
        self.assertEqual(queue["total"], 4)
        self.assertEqual(counts["pending"], 2)
        self.assertEqual(counts["success"], 1)
        self.assertEqual(counts["failed"], 1)
        self.assertEqual(counts["unavailable"], 0)
        self.assertEqual(queue["last_success_at"], scraped_at)


_SCRAPE_DELAY = "ddcs.metadata.dashboard.views.scrape_pending_videos.delay"


class ScraperCooldownDashboardTests(TestCase):
    def setUp(self):
        self.url = reverse("metadata:dashboard")
        cache.clear()
        self.addCleanup(cache.clear)
        self.client.force_login(
            get_user_model().objects.create_superuser(
                username="admin", password="x", email="admin@example.com"
            )
        )
        refresh_patcher = patch(_REQUEST_REFRESH)
        self.request_refresh = refresh_patcher.start()
        self.addCleanup(refresh_patcher.stop)

    def test_queue_reports_active_cooldown_only(self):
        self.assertIsNone(get_scraper_queue()["cooldown"])

        until = register_abort()
        register_abort()

        cooldown = get_scraper_queue()["cooldown"]
        self.assertEqual(cooldown["consecutive_aborts"], 2)
        self.assertGreater(cooldown["until"], until)

        expired = timezone.now() + timedelta(hours=3)
        with patch("ddcs.metadata.scraper.service.timezone.now", return_value=expired):
            self.assertIsNone(get_scraper_queue()["cooldown"])

    @override_settings(TIKTOK_SCRAPER_ENABLED=True)
    def test_paused_notice_shows_how_to_resume(self):
        register_abort()

        response = self.client.get(self.url)

        self.assertContains(response, "Scraping is paused until")
        self.assertContains(response, "after 1 aborted run in a row")
        self.assertContains(response, "Resume scraping now")
        self.assertContains(response, 'name="action" value="resume_scraper"')
        self.assertContains(response, "clear_cooldown()")
        self.assertContains(response, "scrape_pending_videos.delay()")

    @override_settings(TIKTOK_SCRAPER_ENABLED=False)
    def test_no_resume_button_while_the_scraper_is_disabled(self):
        register_abort()

        response = self.client.get(self.url)

        self.assertContains(response, "Scraping is paused until")
        self.assertNotContains(response, "Resume scraping now")
        self.assertContains(response, "clear_cooldown()")

    def test_last_run_shows_why_it_was_aborted(self):
        stats = {
            "scraped": 0,
            "unavailable": 0,
            "failed": 0,
            "blocked": 0,
            "covered_by_api": 0,
            "captions_fetched": 0,
            "captions_failed": 0,
            "aborted": True,
            "seconds": 6.0,
            "videos_per_minute": 50.0,
        }
        for reason, text in (
            ("blocked", "TikTok refused several requests in a row"),
            ("consecutive_failures", "several videos in a row returned no usable data"),
        ):
            with self.subTest(reason=reason):
                record_last_run({**stats, "abort_reason": reason})
                self.assertContains(self.client.get(self.url), text)

    @override_settings(TIKTOK_SCRAPER_ENABLED=True)
    def test_resume_clears_cooldown_queues_a_run_and_redirects(self):
        register_abort()
        url = f"{self.url}?start=2026-08-01&end=2026-08-31"

        with patch(_SCRAPE_DELAY) as delay:
            response = self.client.post(url, {"action": "resume_scraper"})

        self.assertRedirects(response, url, fetch_redirect_response=False)
        self.assertIsNone(get_cooldown())
        delay.assert_called_once_with()
        self.request_refresh.assert_not_called()

    @override_settings(TIKTOK_SCRAPER_ENABLED=False)
    def test_resume_queues_no_run_while_the_scraper_is_disabled(self):
        register_abort()

        with patch(_SCRAPE_DELAY) as delay:
            self.client.post(self.url, {"action": "resume_scraper"})

        self.assertIsNone(get_cooldown())
        delay.assert_not_called()

    @override_settings(TIKTOK_SCRAPER_ENABLED=True)
    def test_refresh_button_still_refreshes_and_leaves_the_scraper_alone(self):
        register_abort()

        with patch(_SCRAPE_DELAY) as delay:
            self.client.post(self.url)

        self.request_refresh.assert_called_once_with()
        delay.assert_not_called()
        self.assertIsNotNone(get_cooldown())
