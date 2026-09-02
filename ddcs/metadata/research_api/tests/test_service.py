from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock, call, patch

from celery.exceptions import SoftTimeLimitExceeded
from django.db import OperationalError
from django.test import TestCase, override_settings
from django.utils import timezone
from tiktok_metadata_kit.research_api import (
    ResearchAPIAccessTokenRetrievalError,
    ResearchAPIRateLimitExceededError,
)

from ddcs.metadata.models import (
    DataOrigins,
    Keyword,
    ResearchAPIQueryTracker,
    SyncAttempt,
    TikTokHashtag,
    TikTokMusic,
    TikTokUser,
    TikTokVideo,
)
from ddcs.metadata.research_api.models import (
    APIVideoInfos,
    APIVideoStatistics,
)
from ddcs.metadata.research_api.service import ResearchAPIService
from ddcs.metadata.research_api.tasks import (
    _STALE_TRACKER_MAX_AGE,
    _USER_SYNC_TARGET_CONFIG,
    _backfill_target_dates,
    _gap_items,
    _Retry,
    _run_query_task,
    backfill_missing_syncs,
    daily_sync_keywords,
    daily_sync_users,
    reap_stale_query_trackers,
)


def make_api_payload(**overrides) -> dict:
    """Sample Research API video payload, with optional field overrides."""
    payload = {
        "id": 7100000000000000001,
        "username": "alice",
        "music_id": 6900000000000000001,
        "create_time": 1700000000,
        "video_description": "hello world",
        "region_code": "US",
        "video_duration": 42,
        "voice_to_text": "hi there",
        "is_stem_verified": False,
        "video_mention_list": ["@bob"],
        "video_label": {"foo": "bar"},
        "view_count": 1000,
        "like_count": 100,
        "comment_count": 10,
        "share_count": 5,
        "favorites_count": 2,
        "hashtag_info_list": [
            {
                "hashtag_id": 5500000000000000001,
                "hashtag_name": "fyp",
                "hashtag_description": "for you page",
            },
        ],
        "hashtag_names": ["fyp", "fmp"],
    }
    payload.update(overrides)
    return payload


@override_settings(TIKTOK_API_KEY="test-key", TIKTOK_API_SECRET="test-secret")
class ResearchAPIServiceCleanTests(TestCase):
    """Test pure mapping helpers"""

    def setUp(self):
        with patch("ddcs.metadata.research_api.service.ResearchAPIClient"):
            self.service = ResearchAPIService()

    def test_clean_video_maps_all_fields(self):
        result = ResearchAPIService._clean_video(make_api_payload())

        self.assertEqual(result["description"], "hello world")
        self.assertEqual(
            result["create_time"],
            datetime.fromtimestamp(1700000000, tz=UTC),
        )
        self.assertEqual(result["region_code"], "US")
        self.assertEqual(result["duration"], 42)
        self.assertEqual(result["voice_to_text"], "hi there")
        self.assertFalse(result["is_stem_verified"])
        self.assertEqual(result["video_mention_list"], ["@bob"])
        self.assertEqual(result["video_label"], {"foo": "bar"})

    def test_clean_video_handles_missing_create_time(self):
        payload = make_api_payload()
        del payload["create_time"]

        result = ResearchAPIService._clean_video(payload)

        self.assertIsNone(result["create_time"])

    def test_clean_video_defaults_for_missing_fields(self):
        result = ResearchAPIService._clean_video({})

        self.assertEqual(result["description"], "")
        self.assertEqual(result["region_code"], "")
        self.assertEqual(result["voice_to_text"], "")
        self.assertIsNone(result["duration"])
        self.assertIsNone(result["is_stem_verified"])

    def test_clean_video_statistics(self):
        result = ResearchAPIService._clean_video_statistics(make_api_payload())

        self.assertEqual(result["view_count"], 1000)
        self.assertEqual(result["like_count"], 100)
        self.assertEqual(result["comment_count"], 10)
        self.assertEqual(result["share_count"], 5)
        self.assertEqual(result["favorites_count"], 2)

    def test_clean_hashtag(self):
        result = ResearchAPIService._clean_hashtag(
            {"hashtag_name": "fyp", "hashtag_description": "for you page"}
        )
        self.assertEqual(result, {"description": "for you page"})


@override_settings(TIKTOK_API_KEY="test-key", TIKTOK_API_SECRET="test-secret")
class ResearchAPIServiceSyncTests(TestCase):
    """Tests for the internal _sync_* helpers."""

    def setUp(self):
        with patch("ddcs.metadata.research_api.service.ResearchAPIClient"):
            self.service = ResearchAPIService()

    def test_sync_user_creates_new(self):
        user = self.service._sync_user("alice")

        self.assertEqual(user.name, "alice")
        self.assertEqual(user.added_by, DataOrigins.RESEARCH_API)
        self.assertEqual(self.service.sync_stats["users_created"], 1)

    def test_sync_user_reuses_existing(self):
        existing = TikTokUser.objects.create(
            name="alice", added_by=DataOrigins.DONATION
        )

        user = self.service._sync_user("alice")

        self.assertEqual(user.pk, existing.pk)
        self.assertEqual(user.added_by, DataOrigins.DONATION)
        self.assertEqual(self.service.sync_stats["users_created"], 0)

    def test_sync_music_returns_none_for_missing_id(self):
        self.assertIsNone(self.service._sync_music(None))
        self.assertIsNone(self.service._sync_music(0))
        self.assertEqual(self.service.sync_stats["music_created"], 0)

    def test_sync_music_creates_and_dedupes(self):
        music = self.service._sync_music(123)
        again = self.service._sync_music(123)

        self.assertEqual(music.pk, again.pk)
        self.assertEqual(music.id_tiktok, 123)
        self.assertEqual(music.added_by, DataOrigins.RESEARCH_API)
        self.assertEqual(self.service.sync_stats["music_created"], 1)

    def test_sync_video_creates_video_and_infos(self):
        user = TikTokUser.objects.create(
            name="alice", added_by=DataOrigins.RESEARCH_API
        )
        payload = make_api_payload()

        video = self.service._sync_video(payload, user=user, music=None)

        self.assertEqual(video.id_tiktok, payload["id"])
        self.assertEqual(video.user, user)
        self.assertIsNone(video.music)
        self.assertEqual(video.added_by, DataOrigins.RESEARCH_API)
        self.assertIsNotNone(video.inferred_create_time)
        self.assertEqual(video.api_infos.count(), 1)
        self.assertEqual(self.service.sync_stats["videos_created"], 1)

    def test_sync_video_does_not_duplicate_infos(self):
        user = TikTokUser.objects.create(
            name="alice", added_by=DataOrigins.RESEARCH_API
        )
        payload = make_api_payload()

        self.service._sync_video(payload, user=user, music=None)
        self.service._sync_video(payload, user=user, music=None)

        video = TikTokVideo.objects.get(id_tiktok=payload["id"])
        self.assertEqual(video.api_infos.count(), 1)
        self.assertEqual(self.service.sync_stats["videos_created"], 1)

    def test_sync_video_statistics_appends_each_call(self):
        user = TikTokUser.objects.create(
            name="alice", added_by=DataOrigins.RESEARCH_API
        )
        video = self.service._sync_video(make_api_payload(), user=user, music=None)

        self.service._sync_video_statistics(make_api_payload(), video=video)
        self.service._sync_video_statistics(
            make_api_payload(view_count=2000), video=video
        )

        stats = APIVideoStatistics.objects.filter(video=video).order_by("pk")
        self.assertEqual(stats.count(), 2)
        self.assertEqual(stats.last().view_count, 2000)

    def test_sync_hashtag_creates_new_with_infos(self):
        hashtag_data = {
            "hashtag_id": 999,
            "hashtag_name": "fyp",
            "hashtag_description": "for you page",
        }

        hashtag = self.service._sync_hashtag(hashtag_data)

        self.assertEqual(hashtag.name, "fyp")
        self.assertEqual(hashtag.id_tiktok, 999)
        self.assertEqual(hashtag.added_by, DataOrigins.RESEARCH_API)
        self.assertEqual(hashtag.api_infos.count(), 1)
        self.assertEqual(self.service.sync_stats["hashtags_created"], 1)

    def test_sync_hashtag_backfills_id_tiktok_on_existing(self):
        TikTokHashtag.objects.create(
            name="fyp", added_by=DataOrigins.SCRAPER, id_tiktok=None
        )

        hashtag = self.service._sync_hashtag(
            {
                "hashtag_id": 999,
                "hashtag_name": "fyp",
                "hashtag_description": "",
            }
        )

        self.assertEqual(hashtag.id_tiktok, 999)
        self.assertEqual(self.service.sync_stats["hashtags_created"], 0)

    def test_sync_hashtag_name_creates_new_hashtag(self):
        name = "new_hashtag"
        self.service._sync_hashtag_name(name)
        self.assertTrue(TikTokHashtag.objects.filter(name=name).exists())

    def test_sync_hashtags_attaches_to_video(self):
        user = TikTokUser.objects.create(
            name="alice", added_by=DataOrigins.RESEARCH_API
        )
        video = self.service._sync_video(make_api_payload(), user=user, music=None)

        self.service._sync_hashtags(["a", "b"], video=video)

        names = set(video.hashtags.values_list("name", flat=True))
        self.assertEqual(names, {"a", "b"})


@override_settings(TIKTOK_API_KEY="test-key", TIKTOK_API_SECRET="test-secret")
class ResearchAPIServiceProcessTests(TestCase):
    """End-to-end through _process_api_response."""

    def setUp(self):
        with patch("ddcs.metadata.research_api.service.ResearchAPIClient"):
            self.service = ResearchAPIService()

    def test_process_api_response_persists_full_graph(self):
        payload = make_api_payload()

        self.service._process_api_response(payload)

        user = TikTokUser.objects.get(name="alice")
        music = TikTokMusic.objects.get(id_tiktok=payload["music_id"])
        video = TikTokVideo.objects.get(id_tiktok=payload["id"])

        self.assertEqual(video.user, user)
        self.assertEqual(video.music, music)
        self.assertEqual(video.api_infos.count(), 1)
        self.assertEqual(video.statistics.count(), 1)

        infos = video.api_infos.get()
        self.assertEqual(infos.description, "hello world")
        self.assertEqual(infos.region_code, "US")

        hashtags = video.hashtags.all()
        self.assertEqual(len(hashtags), 2)

    def test_process_api_response_handles_missing_music(self):
        payload = make_api_payload(music_id=None)

        self.service._process_api_response(payload)

        video = TikTokVideo.objects.get(id_tiktok=payload["id"])
        self.assertIsNone(video.music)
        self.assertEqual(TikTokMusic.objects.count(), 0)

    def test_process_api_response_idempotent_on_replay(self):
        payload = make_api_payload()

        self.service._process_api_response(payload)
        self.service._process_api_response(payload)

        video = TikTokVideo.objects.get(id_tiktok=payload["id"])
        self.assertEqual(TikTokVideo.objects.count(), 1)
        self.assertEqual(TikTokUser.objects.count(), 1)
        self.assertEqual(TikTokHashtag.objects.count(), 2)
        self.assertEqual(APIVideoInfos.objects.count(), 1)
        # Statistics are appended on every sync — two calls, two rows.
        self.assertEqual(video.statistics.count(), 2)


@override_settings(TIKTOK_API_KEY="test-key", TIKTOK_API_SECRET="test-secret")
class ResearchAPIServiceGetUserVideosTests(TestCase):
    """Verifies the public entry point wires the client through correctly."""

    def test_get_user_videos_iterates_client_and_persists(self):
        pages = [
            {
                "data": {
                    "videos": [
                        make_api_payload(id=7100000000000000001, username="alice")
                    ]
                }
            },
            {
                "data": {
                    "videos": [
                        make_api_payload(
                            id=7100000000000000002, username="bob", music_id=None
                        )
                    ]
                }
            },
        ]

        expected_query = {
            "and": [
                {
                    "operation": "IN",
                    "field_name": "username",
                    "field_values": ["alice", "bob"],
                }
            ]
        }

        with patch(
            "ddcs.metadata.research_api.service.ResearchAPIClient"
        ) as client_cls:
            client_cls.return_value.query_videos_pages.return_value = iter(pages)
            service = ResearchAPIService()
            service.get_user_videos(["alice", "bob"], start_date="x", end_date="y")

            client_cls.return_value.query_videos_pages.assert_called_once_with(
                expected_query, start_date="x", end_date="y"
            )

        self.assertEqual(TikTokVideo.objects.count(), 2)
        self.assertEqual(
            set(TikTokUser.objects.values_list("name", flat=True)), {"alice", "bob"}
        )
        self.assertEqual(service.sync_stats["videos_created"], 2)
        self.assertEqual(service.sync_stats["users_created"], 2)

    def _run_with_failing_process(self, exc: Exception) -> tuple[MagicMock, Exception]:
        page = {"data": {"videos": [make_api_payload()]}}
        with patch(
            "ddcs.metadata.research_api.service.ResearchAPIClient"
        ) as client_cls:
            client_cls.return_value.query_videos_pages.return_value = iter([page])
            service = ResearchAPIService()

        with (
            patch("ddcs.metadata.research_api.service.logger") as log_mock,
            patch.object(service, "_process_api_response", side_effect=exc),
            self.assertRaises(type(exc)) as caught,
        ):
            service.get_user_videos(["alice"], start_date="x", end_date="y")
        return log_mock, caught.exception

    def test_soft_time_limit_reraised_without_payload_dump(self):
        log_mock, _ = self._run_with_failing_process(SoftTimeLimitExceeded())
        log_mock.exception.assert_not_called()

    def test_generic_processing_error_still_logs_payload(self):
        log_mock, _ = self._run_with_failing_process(RuntimeError("boom"))
        log_mock.exception.assert_called_once()


_TWO_PAIRS = [("k1", "s1"), ("k2", "s2")]


@patch("ddcs.metadata.research_api.service.mark_credentials_exhausted")
@patch(
    "ddcs.metadata.research_api.service.is_credentials_exhausted", return_value=False
)
@patch("ddcs.metadata.research_api.service.get_research_api_credentials")
@patch("ddcs.metadata.research_api.service.ResearchAPIClient")
class ResearchAPIServiceCredentialFailoverTests(TestCase):
    """Fail-over to the secondary credential pair on a rate limit."""

    @staticmethod
    def _page(video_id: int, username: str) -> dict:
        return {"data": {"videos": [make_api_payload(id=video_id, username=username)]}}

    def test_switches_to_secondary_on_rate_limit(
        self, client_cls, creds_mock, exh_mock, mark_mock
    ):
        creds_mock.return_value = _TWO_PAIRS
        inst1, inst2 = MagicMock(), MagicMock()
        client_cls.side_effect = [inst1, inst2]
        inst1.query_videos_pages.side_effect = ResearchAPIRateLimitExceededError("x")
        inst2.query_videos_pages.return_value = iter(
            [self._page(7100000000000000001, "alice")]
        )

        service = ResearchAPIService()
        service.get_user_videos(["alice"], start_date="x", end_date="y")

        self.assertEqual(service.sync_stats["credential_switches"], 1)
        self.assertEqual(service._credential_index, 1)
        self.assertEqual(
            client_cls.call_args_list[1].kwargs,
            {"api_key": "k2", "api_secret": "s2"},
        )
        inst1.close.assert_called_once()
        mark_mock.assert_called_once_with(0)
        self.assertEqual(TikTokVideo.objects.count(), 1)

    def test_only_primary_configured_rate_limit_propagates(
        self, client_cls, creds_mock, exh_mock, mark_mock
    ):
        creds_mock.return_value = [("k1", "s1")]
        client_cls.return_value.query_videos_pages.side_effect = (
            ResearchAPIRateLimitExceededError("x")
        )

        service = ResearchAPIService()
        with self.assertRaises(ResearchAPIRateLimitExceededError):
            service.get_user_videos(["alice"])

        self.assertEqual(service.sync_stats["credential_switches"], 0)
        mark_mock.assert_not_called()

    def test_both_pairs_rate_limited_raises(
        self, client_cls, creds_mock, exh_mock, mark_mock
    ):
        creds_mock.return_value = _TWO_PAIRS
        inst1, inst2 = MagicMock(), MagicMock()
        client_cls.side_effect = [inst1, inst2]
        inst1.query_videos_pages.side_effect = ResearchAPIRateLimitExceededError("x")
        inst2.query_videos_pages.side_effect = ResearchAPIRateLimitExceededError("x")

        service = ResearchAPIService()
        with self.assertRaises(ResearchAPIRateLimitExceededError):
            service.get_user_videos(["alice"])

        # One switch happened; only the abandoned primary is flagged (there is
        # nothing to fall back to past the last pair).
        self.assertEqual(service.sync_stats["credential_switches"], 1)
        self.assertEqual(mark_mock.call_args_list, [call(0)])

    def test_starts_on_secondary_when_primary_hint_live(
        self, client_cls, creds_mock, exh_mock, mark_mock
    ):
        creds_mock.return_value = _TWO_PAIRS
        exh_mock.side_effect = lambda idx: idx == 0

        service = ResearchAPIService()

        self.assertEqual(service._credential_index, 1)
        client_cls.assert_called_once_with(api_key="k2", api_secret="s2")

    def test_secondary_token_fetch_fails_during_advance(
        self, client_cls, creds_mock, exh_mock, mark_mock
    ):
        creds_mock.return_value = _TWO_PAIRS
        inst1 = MagicMock()
        inst1.query_videos_pages.side_effect = ResearchAPIRateLimitExceededError("x")
        client_cls.side_effect = [
            inst1,
            ResearchAPIAccessTokenRetrievalError("nope"),
        ]

        service = ResearchAPIService()
        with self.assertRaises(ResearchAPIRateLimitExceededError):
            service.get_user_videos(["alice"])

        self.assertEqual(service.sync_stats["credential_switches"], 0)
        mark_mock.assert_called_once_with(0)

    def test_restart_is_idempotent_for_statistics(
        self, client_cls, creds_mock, exh_mock, mark_mock
    ):
        creds_mock.return_value = _TWO_PAIRS
        inst1, inst2 = MagicMock(), MagicMock()
        client_cls.side_effect = [inst1, inst2]
        rate_limit = ResearchAPIRateLimitExceededError("x")

        def primary_pages(*_args, **_kwargs):
            yield self._page(7100000000000000001, "alice")
            raise rate_limit

        inst1.query_videos_pages.side_effect = primary_pages
        inst2.query_videos_pages.side_effect = lambda *a, **k: iter(
            [
                self._page(7100000000000000001, "alice"),
                self._page(7100000000000000002, "bob"),
            ]
        )

        service = ResearchAPIService()
        service.get_user_videos(["alice"])

        self.assertEqual(TikTokVideo.objects.count(), 2)
        self.assertEqual(
            APIVideoStatistics.objects.filter(
                video__id_tiktok=7100000000000000001
            ).count(),
            1,
        )
        self.assertEqual(service.sync_stats["videos_retrieved"], 2)

    def test_soft_time_limit_does_not_trigger_failover(
        self, client_cls, creds_mock, exh_mock, mark_mock
    ):
        creds_mock.return_value = _TWO_PAIRS
        inst1 = MagicMock()
        client_cls.side_effect = [inst1, MagicMock()]
        inst1.query_videos_pages.return_value = iter(
            [self._page(7100000000000000001, "alice")]
        )

        service = ResearchAPIService()
        with (
            patch.object(
                service, "_process_api_response", side_effect=SoftTimeLimitExceeded()
            ),
            self.assertRaises(SoftTimeLimitExceeded),
        ):
            service.get_user_videos(["alice"])

        self.assertEqual(service.sync_stats["credential_switches"], 0)
        mark_mock.assert_not_called()

    def test_feature_dormant_when_single_pair(
        self, client_cls, creds_mock, exh_mock, mark_mock
    ):
        creds_mock.return_value = [("k1", "s1")]

        ResearchAPIService()

        exh_mock.assert_not_called()


TARGET = date(2025, 6, 10)


def _monitored_user(name: str, priority: int = 0) -> TikTokUser:
    return TikTokUser.objects.create(
        name=name, monitor_api=True, monitoring_priority_api=priority
    )


def _monitored_keyword(name: str, priority: int = 0) -> Keyword:
    return Keyword.objects.create(
        name=name, monitor_api=True, monitoring_priority_api=priority
    )


def _configure_service_mock(cls_mock, pages_per_call: int = 0):
    """Seed sync_stats with a real dict so tracker save doesn't choke on MagicMock.

    ``pages_per_call`` optionally makes the mocked ``get_user_videos`` and
    ``get_videos_by_keywords`` bump ``sync_stats["pages_retrieved"]`` by that
    many on each call — useful for asserting quota-budget behavior.
    """
    stats = {
        "users_created": 0,
        "videos_created": 0,
        "hashtags_created": 0,
        "music_created": 0,
        "videos_retrieved": 0,
        "pages_retrieved": 0,
        "credential_switches": 0,
    }
    cls_mock.return_value.sync_stats = stats

    if pages_per_call:

        def _bump(*args, **kwargs):
            stats["pages_retrieved"] += pages_per_call

        cls_mock.return_value.get_user_videos.side_effect = _bump
        cls_mock.return_value.get_videos_by_keywords.side_effect = _bump

    return cls_mock


class GapItemsTest(TestCase):
    """Verifies which monitored items are considered gaps for a target_date."""

    def test_excludes_items_with_successful_attempt_for_that_date(self):
        u1 = _monitored_user("u1")
        u2 = _monitored_user("u2")
        SyncAttempt.objects.create(
            user=u1, target_date=TARGET, status=SyncAttempt.Status.SUCCESS
        )

        gaps = list(
            _gap_items(_USER_SYNC_TARGET_CONFIG, TARGET).values_list("id", flat=True)
        )
        self.assertEqual(gaps, [u2.id])

    def test_success_on_different_date_still_counts_as_gap(self):
        u = _monitored_user("u1")
        SyncAttempt.objects.create(
            user=u,
            target_date=TARGET - timedelta(days=1),
            status=SyncAttempt.Status.SUCCESS,
        )

        gaps = list(
            _gap_items(_USER_SYNC_TARGET_CONFIG, TARGET).values_list("id", flat=True)
        )
        self.assertEqual(gaps, [u.id])

    def test_failed_attempts_do_not_close_gap(self):
        u = _monitored_user("u1")
        SyncAttempt.objects.create(
            user=u, target_date=TARGET, status=SyncAttempt.Status.API_ERROR
        )

        gaps = list(
            _gap_items(_USER_SYNC_TARGET_CONFIG, TARGET).values_list("id", flat=True)
        )
        self.assertEqual(gaps, [u.id])

    def test_ignores_unmonitored_items(self):
        TikTokUser.objects.create(name="ghost", monitor_api=False)
        u = _monitored_user("real")

        gaps = list(
            _gap_items(_USER_SYNC_TARGET_CONFIG, TARGET).values_list("id", flat=True)
        )
        self.assertEqual(gaps, [u.id])

    def test_force_resync_bypasses_success_filter(self):
        u1 = _monitored_user("u1")
        u2 = _monitored_user("u2")
        SyncAttempt.objects.create(
            user=u1, target_date=TARGET, status=SyncAttempt.Status.SUCCESS
        )

        # Normal filter: u1 already synced, only u2 is a gap.
        normal = list(
            _gap_items(_USER_SYNC_TARGET_CONFIG, TARGET).values_list("id", flat=True)
        )
        forced = list(
            _gap_items(_USER_SYNC_TARGET_CONFIG, TARGET, force_resync=True).values_list(
                "id", flat=True
            )
        )

        self.assertEqual(normal, [u2.id])
        self.assertEqual(set(forced), {u1.id, u2.id})

    def test_ordered_by_monitoring_priority_desc(self):
        low = _monitored_user("low", priority=0)
        high = _monitored_user("high", priority=10)
        mid = _monitored_user("mid", priority=5)

        ordered = list(
            _gap_items(_USER_SYNC_TARGET_CONFIG, TARGET).values_list("id", flat=True)
        )
        self.assertEqual(ordered, [high.id, mid.id, low.id])


class RunQueryTaskTest(TestCase):
    """End-to-end for the shared runner, per outcome branch."""

    def setUp(self):
        self.u1 = _monitored_user("u1")
        self.u2 = _monitored_user("u2")
        # The recovery-path handlers call `_recover_db_connection()`, which
        # does a real `connection.close()`. Doing that mid-test would tear
        # down the `TestCase` transaction, so neutralize it here and expose
        # the mock for assertions.
        recover_patcher = patch(
            "ddcs.metadata.research_api.tasks._recover_db_connection"
        )
        self.recover_mock = recover_patcher.start()
        self.addCleanup(recover_patcher.stop)

    @patch("ddcs.metadata.research_api.tasks.ResearchAPIService")
    def test_success_writes_success_syncattempts_and_returns_none(self, cls_mock):
        _configure_service_mock(cls_mock)
        result = _run_query_task(_USER_SYNC_TARGET_CONFIG, TARGET, batch_size=10)

        self.assertIs(result.retry, _Retry.NONE)
        cls_mock.return_value.get_user_videos.assert_called_once()
        attempts = SyncAttempt.objects.filter(target_date=TARGET)
        self.assertEqual(attempts.count(), 2)
        self.assertTrue(all(a.status == SyncAttempt.Status.SUCCESS for a in attempts))
        self.assertTrue(all(a.tracker is not None for a in attempts))

    @patch("ddcs.metadata.research_api.tasks.ResearchAPIService")
    def test_rate_limit_writes_rate_limited_and_returns_same_batch(self, cls_mock):
        _configure_service_mock(cls_mock)
        cls_mock.return_value.get_user_videos.side_effect = (
            ResearchAPIRateLimitExceededError("throttled")
        )

        result = _run_query_task(_USER_SYNC_TARGET_CONFIG, TARGET, batch_size=10)

        self.assertIs(result.retry, _Retry.SAME_BATCH)
        attempts = SyncAttempt.objects.filter(target_date=TARGET)
        self.assertEqual(attempts.count(), 2)
        self.assertTrue(
            all(a.status == SyncAttempt.Status.RATE_LIMITED for a in attempts)
        )

    @patch("ddcs.metadata.research_api.tasks.ResearchAPIService")
    def test_soft_time_limit_writes_timeout_and_returns_halve_batch(self, cls_mock):
        _configure_service_mock(cls_mock)
        cls_mock.return_value.get_user_videos.side_effect = SoftTimeLimitExceeded()

        result = _run_query_task(_USER_SYNC_TARGET_CONFIG, TARGET, batch_size=10)

        self.assertIs(result.retry, _Retry.HALVE_BATCH)
        self.assertEqual(
            SyncAttempt.objects.filter(
                target_date=TARGET, status=SyncAttempt.Status.TIMEOUT
            ).count(),
            2,
        )

    @patch("ddcs.metadata.research_api.tasks.ResearchAPIService")
    def test_partial_failure_writes_api_error_and_returns_halve_batch(self, cls_mock):
        _configure_service_mock(cls_mock)
        # batch_size=1 → two batches; second raises
        cls_mock.return_value.get_user_videos.side_effect = [None, RuntimeError("boom")]

        result = _run_query_task(_USER_SYNC_TARGET_CONFIG, TARGET, batch_size=1)

        self.assertIs(result.retry, _Retry.HALVE_BATCH)
        successes = SyncAttempt.objects.filter(
            target_date=TARGET, status=SyncAttempt.Status.SUCCESS
        )
        errors = SyncAttempt.objects.filter(
            target_date=TARGET, status=SyncAttempt.Status.API_ERROR
        )
        self.assertEqual(successes.count(), 1)
        self.assertEqual(errors.count(), 1)
        self.assertIn("boom", errors.first().error_details["message"])

    @patch("ddcs.metadata.research_api.tasks.ResearchAPIService")
    def test_rate_limit_after_earlier_failure_preserves_failed_batches_on_tracker(
        self, cls_mock
    ):
        # Batch 1 fails with a generic exception (goes into failed_batches).
        # Batch 2 hits the rate limit — the early-exit path must still write
        # the accumulated failed_batches to tracker.query_exception_details.
        _configure_service_mock(cls_mock)
        cls_mock.return_value.get_user_videos.side_effect = [
            RuntimeError("first-batch boom"),
            ResearchAPIRateLimitExceededError("throttled"),
        ]

        _run_query_task(_USER_SYNC_TARGET_CONFIG, TARGET, batch_size=1)

        tracker = ResearchAPIQueryTracker.objects.latest("start_time")
        self.assertEqual(
            tracker.query_status,
            ResearchAPIQueryTracker.Status.RATE_LIMIT_EXCEEDED,
        )
        self.assertIsNotNone(tracker.query_exception_details)
        failed = tracker.query_exception_details["failed batches"]
        self.assertEqual(len(failed), 1)
        self.assertIn("first-batch boom", failed[0]["error"])

    @patch("ddcs.metadata.research_api.tasks.ResearchAPIService")
    def test_no_gaps_returns_none_without_calling_api(self, cls_mock):
        _configure_service_mock(cls_mock)
        SyncAttempt.objects.create(
            user=self.u1, target_date=TARGET, status=SyncAttempt.Status.SUCCESS
        )
        SyncAttempt.objects.create(
            user=self.u2, target_date=TARGET, status=SyncAttempt.Status.SUCCESS
        )

        result = _run_query_task(_USER_SYNC_TARGET_CONFIG, TARGET, batch_size=10)

        self.assertIs(result.retry, _Retry.NONE)
        cls_mock.return_value.get_user_videos.assert_not_called()

    # --- connection recovery on the failure paths ---------------------

    @patch("ddcs.metadata.research_api.tasks.ResearchAPIService")
    def test_soft_time_limit_recovers_connection_before_bookkeeping(self, cls_mock):
        _configure_service_mock(cls_mock)
        cls_mock.return_value.get_user_videos.side_effect = SoftTimeLimitExceeded()

        result = _run_query_task(_USER_SYNC_TARGET_CONFIG, TARGET, batch_size=10)

        self.recover_mock.assert_called()
        self.assertIs(result.retry, _Retry.HALVE_BATCH)
        self.assertEqual(
            SyncAttempt.objects.filter(
                target_date=TARGET, status=SyncAttempt.Status.TIMEOUT
            ).count(),
            2,
        )
        tracker = ResearchAPIQueryTracker.objects.latest("start_time")
        self.assertEqual(
            tracker.query_status,
            ResearchAPIQueryTracker.Status.SOFT_TIME_LIMIT_EXCEEDED,
        )
        self.assertIsNotNone(tracker.end_time)

    @patch("ddcs.metadata.research_api.tasks.ResearchAPIService")
    def test_rate_limit_recovers_connection_before_bookkeeping(self, cls_mock):
        _configure_service_mock(cls_mock)
        cls_mock.return_value.get_user_videos.side_effect = (
            ResearchAPIRateLimitExceededError("throttled")
        )

        result = _run_query_task(_USER_SYNC_TARGET_CONFIG, TARGET, batch_size=10)

        self.recover_mock.assert_called()
        self.assertIs(result.retry, _Retry.SAME_BATCH)
        self.assertEqual(
            SyncAttempt.objects.filter(
                target_date=TARGET, status=SyncAttempt.Status.RATE_LIMITED
            ).count(),
            2,
        )
        tracker = ResearchAPIQueryTracker.objects.latest("start_time")
        self.assertEqual(
            tracker.query_status,
            ResearchAPIQueryTracker.Status.RATE_LIMIT_EXCEEDED,
        )

    @patch("ddcs.metadata.research_api.tasks.ResearchAPIService")
    def test_generic_batch_error_recovers_connection(self, cls_mock):
        _configure_service_mock(cls_mock)
        cls_mock.return_value.get_user_videos.side_effect = [None, RuntimeError("boom")]

        result = _run_query_task(_USER_SYNC_TARGET_CONFIG, TARGET, batch_size=1)

        self.recover_mock.assert_called()
        self.assertIs(result.retry, _Retry.HALVE_BATCH)
        self.assertEqual(
            SyncAttempt.objects.filter(
                target_date=TARGET, status=SyncAttempt.Status.SUCCESS
            ).count(),
            1,
        )
        self.assertEqual(
            SyncAttempt.objects.filter(
                target_date=TARGET, status=SyncAttempt.Status.API_ERROR
            ).count(),
            1,
        )

    @patch("ddcs.metadata.research_api.tasks._record_sync_attempts")
    @patch("ddcs.metadata.research_api.tasks.ResearchAPIService")
    def test_recovery_bookkeeping_failure_does_not_escape_and_tracker_finalized(
        self, cls_mock, record_mock
    ):
        _configure_service_mock(cls_mock)
        cls_mock.return_value.get_user_videos.side_effect = SoftTimeLimitExceeded()
        # The sync-attempt write still fails after reconnecting; the tracker
        # finalize is guarded separately and must still run.
        record_mock.side_effect = OperationalError("connection already closed")

        result = _run_query_task(_USER_SYNC_TARGET_CONFIG, TARGET, batch_size=10)

        self.assertIs(result.retry, _Retry.HALVE_BATCH)
        tracker = ResearchAPIQueryTracker.objects.latest("start_time")
        self.assertEqual(
            tracker.query_status,
            ResearchAPIQueryTracker.Status.SOFT_TIME_LIMIT_EXCEEDED,
        )

    @patch("ddcs.metadata.research_api.tasks.update_query_tracker")
    @patch("ddcs.metadata.research_api.tasks.ResearchAPIService")
    def test_recovery_tracker_write_failure_is_swallowed(self, cls_mock, update_mock):
        _configure_service_mock(cls_mock)
        cls_mock.return_value.get_user_videos.side_effect = SoftTimeLimitExceeded()
        update_mock.side_effect = OperationalError("connection already closed")

        # No exception escapes; the retry decision is still returned so the
        # outer task can re-queue. The stranded tracker is left to the reaper.
        result = _run_query_task(_USER_SYNC_TARGET_CONFIG, TARGET, batch_size=10)

        self.assertIs(result.retry, _Retry.HALVE_BATCH)

    @patch(
        "ddcs.metadata.research_api.tasks.get_research_api_credentials",
        return_value=[("k", "s"), ("k2", "s2")],
    )
    @patch("ddcs.metadata.research_api.tasks.ResearchAPIService")
    def test_tracker_records_credentials_available(self, cls_mock, creds_mock):
        _configure_service_mock(cls_mock)

        _run_query_task(_USER_SYNC_TARGET_CONFIG, TARGET, batch_size=10)

        tracker = ResearchAPIQueryTracker.objects.latest("start_time")
        self.assertEqual(tracker.query_parameters["credentials_available"], 2)

    @patch("ddcs.metadata.research_api.tasks.ResearchAPIService")
    def test_credential_switches_flows_to_tracker_result(self, cls_mock):
        _configure_service_mock(cls_mock)
        cls_mock.return_value.sync_stats["credential_switches"] = 1

        _run_query_task(_USER_SYNC_TARGET_CONFIG, TARGET, batch_size=10)

        tracker = ResearchAPIQueryTracker.objects.latest("start_time")
        self.assertEqual(tracker.query_result["credential_switches"], 1)


class ReapStaleQueryTrackersTest(TestCase):
    """The periodic reaper that finalizes trackers stranded in STARTED."""

    @staticmethod
    def _tracker(
        *,
        age: timedelta,
        status: str = ResearchAPIQueryTracker.Status.STARTED,
        ended: bool = False,
    ) -> ResearchAPIQueryTracker:
        start = timezone.now() - age
        return ResearchAPIQueryTracker.objects.create(
            start_time=start,
            end_time=(start + timedelta(minutes=5)) if ended else None,
            query_function="daily_sync_users",
            query_parameters={},
            query_status=status,
        )

    def test_marks_old_started_tracker_failed(self):
        tracker = self._tracker(age=_STALE_TRACKER_MAX_AGE + timedelta(hours=1))

        updated = reap_stale_query_trackers()

        self.assertEqual(updated, 1)
        tracker.refresh_from_db()
        self.assertEqual(tracker.query_status, ResearchAPIQueryTracker.Status.FAILED)
        self.assertIsNotNone(tracker.end_time)
        self.assertIs(tracker.query_exception_details["reaped"], True)

    def test_leaves_recent_started_tracker_alone(self):
        tracker = self._tracker(age=timedelta(minutes=30))

        self.assertEqual(reap_stale_query_trackers(), 0)
        tracker.refresh_from_db()
        self.assertEqual(tracker.query_status, ResearchAPIQueryTracker.Status.STARTED)
        self.assertIsNone(tracker.end_time)

    def test_leaves_finished_tracker_alone(self):
        tracker = self._tracker(
            age=_STALE_TRACKER_MAX_AGE + timedelta(hours=1),
            status=ResearchAPIQueryTracker.Status.COMPLETED,
            ended=True,
        )

        self.assertEqual(reap_stale_query_trackers(), 0)
        tracker.refresh_from_db()
        self.assertEqual(tracker.query_status, ResearchAPIQueryTracker.Status.COMPLETED)

    def test_reaps_multiple(self):
        self._tracker(age=_STALE_TRACKER_MAX_AGE + timedelta(hours=1))
        self._tracker(age=_STALE_TRACKER_MAX_AGE + timedelta(hours=2))
        fresh = self._tracker(age=timedelta(minutes=10))

        self.assertEqual(reap_stale_query_trackers(), 2)
        fresh.refresh_from_db()
        self.assertEqual(fresh.query_status, ResearchAPIQueryTracker.Status.STARTED)


class DailySyncTasksTest(TestCase):
    """The user- and keyword-facing daily task wrappers."""

    @patch("ddcs.metadata.research_api.tasks.ResearchAPIService")
    def test_daily_sync_users_writes_syncattempts_for_target_date(self, cls_mock):
        _configure_service_mock(cls_mock)
        _monitored_user("u1")

        daily_sync_users(target_date="2025-06-10")

        cls_mock.return_value.get_user_videos.assert_called_once()
        self.assertEqual(
            SyncAttempt.objects.filter(
                user__name="u1",
                target_date=date(2025, 6, 10),
                status=SyncAttempt.Status.SUCCESS,
            ).count(),
            1,
        )

    @patch("ddcs.metadata.research_api.tasks.ResearchAPIService")
    def test_daily_sync_keywords_uses_keyword_fk_on_attempts(self, cls_mock):
        _configure_service_mock(cls_mock)
        _monitored_keyword("k1")

        daily_sync_keywords(target_date="2025-06-10")

        cls_mock.return_value.get_videos_by_keywords.assert_called_once()
        attempt = SyncAttempt.objects.get(keyword__name="k1")
        self.assertEqual(attempt.status, SyncAttempt.Status.SUCCESS)
        self.assertIsNone(attempt.user_id)


class BackfillTargetDatesTest(TestCase):
    @override_settings(API_MONITORING_START_DATE=date(2025, 6, 1))
    @patch("ddcs.metadata.research_api.tasks.timezone")
    def test_range_from_today_minus_4_back_to_setting(self, tz_mock):
        tz_mock.localdate.return_value = date(2025, 6, 10)

        dates = _backfill_target_dates()

        self.assertEqual(dates[0], date(2025, 6, 6))
        self.assertEqual(dates[-1], date(2025, 6, 1))
        self.assertEqual(len(dates), 6)

    @override_settings(API_MONITORING_START_DATE=date(2030, 1, 1))
    @patch("ddcs.metadata.research_api.tasks.timezone")
    def test_returns_empty_when_start_is_after_horizon(self, tz_mock):
        tz_mock.localdate.return_value = date(2025, 6, 10)

        self.assertEqual(_backfill_target_dates(), [])


@override_settings(API_MONITORING_START_DATE=date(2025, 6, 1))
class BackfillMissingSyncsTest(TestCase):
    """Verifies priorities, capping, and lock behavior of the backfill task."""

    def _fake_lock(self, acquired: bool = True):  # noqa: FBT002
        lock = MagicMock()
        lock.acquire.return_value = acquired
        return lock

    def _fake_redis(self, lock):
        redis_mock = MagicMock()
        redis_mock.lock.return_value = lock
        return redis_mock

    @patch("ddcs.metadata.research_api.tasks.timezone")
    @patch("ddcs.metadata.research_api.tasks.ResearchAPIService")
    @patch("ddcs.metadata.research_api.tasks.Redis")
    def test_processes_users_before_keywords(self, redis_cls, svc_cls, tz_mock):
        _configure_service_mock(svc_cls)
        tz_mock.localdate.return_value = date(2025, 6, 5)  # single backfill date: 6/1
        tz_mock.now.side_effect = lambda: datetime(2025, 6, 5, tzinfo=UTC)
        redis_cls.from_url.return_value = self._fake_redis(self._fake_lock())
        _monitored_user("u1")
        _monitored_keyword("k1")

        backfill_missing_syncs()

        call_order = [c[0] for c in svc_cls.return_value.mock_calls if c[0]]
        # get_user_videos should be called before get_videos_by_keywords
        first_user = call_order.index("get_user_videos")
        first_keyword = call_order.index("get_videos_by_keywords")
        self.assertLess(first_user, first_keyword)

    @patch("ddcs.metadata.research_api.tasks.timezone")
    @patch("ddcs.metadata.research_api.tasks.ResearchAPIService")
    @patch("ddcs.metadata.research_api.tasks.Redis")
    def test_stops_when_lock_is_held(self, redis_cls, svc_cls, tz_mock):
        tz_mock.localdate.return_value = date(2025, 6, 5)
        redis_cls.from_url.return_value = self._fake_redis(
            self._fake_lock(acquired=False)
        )
        _monitored_user("u1")

        backfill_missing_syncs()

        svc_cls.return_value.get_user_videos.assert_not_called()

    @patch("ddcs.metadata.research_api.tasks.timezone")
    @patch("ddcs.metadata.research_api.tasks.ResearchAPIService")
    @patch("ddcs.metadata.research_api.tasks.Redis")
    def test_stops_on_rate_limit_without_processing_more_pairs(
        self, redis_cls, svc_cls, tz_mock
    ):
        # First (target, date) hits a rate limit; the backfill should exit
        # rather than iterate to the next pair and re-trip the same limit.
        _configure_service_mock(svc_cls)
        svc_cls.return_value.get_user_videos.side_effect = (
            ResearchAPIRateLimitExceededError("throttled")
        )
        tz_mock.localdate.return_value = date(2025, 6, 5)
        tz_mock.now.side_effect = lambda: datetime(2025, 6, 5, tzinfo=UTC)
        redis_cls.from_url.return_value = self._fake_redis(self._fake_lock())
        _monitored_user("u1")
        _monitored_keyword("k1")

        backfill_missing_syncs()

        svc_cls.return_value.get_user_videos.assert_called_once()
        svc_cls.return_value.get_videos_by_keywords.assert_not_called()
