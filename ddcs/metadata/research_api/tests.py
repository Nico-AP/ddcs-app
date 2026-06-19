from datetime import UTC, datetime
from unittest.mock import patch

from django.test import TestCase, override_settings

from ddcs.metadata.models import (
    DataOrigins,
    TikTokHashtag,
    TikTokMusic,
    TikTokUser,
    TikTokVideo,
)
from ddcs.metadata.research_api.models import (
    APIHashtagInfos,
    APIVideoInfos,
    APIVideoStatistics,
)
from ddcs.metadata.research_api.service import ResearchAPIService


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

    def test_sync_hashtags_attaches_to_video(self):
        user = TikTokUser.objects.create(
            name="alice", added_by=DataOrigins.RESEARCH_API
        )
        video = self.service._sync_video(make_api_payload(), user=user, music=None)

        self.service._sync_hashtags(
            [
                {"hashtag_id": 1, "hashtag_name": "a", "hashtag_description": ""},
                {"hashtag_id": 2, "hashtag_name": "b", "hashtag_description": ""},
            ],
            video=video,
        )

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

        hashtag = video.hashtags.get()
        self.assertEqual(hashtag.name, "fyp")
        self.assertEqual(hashtag.id_tiktok, 5500000000000000001)
        self.assertEqual(hashtag.api_infos.get().description, "for you page")

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
        self.assertEqual(TikTokHashtag.objects.count(), 1)
        self.assertEqual(APIVideoInfos.objects.count(), 1)
        self.assertEqual(APIHashtagInfos.objects.count(), 1)
        # Statistics are appended on every sync — two calls, two rows.
        self.assertEqual(video.statistics.count(), 2)


@override_settings(TIKTOK_API_KEY="test-key", TIKTOK_API_SECRET="test-secret")
class ResearchAPIServiceGetUserVideosTests(TestCase):
    """Verifies the public entry point wires the client through correctly."""

    def test_get_user_videos_iterates_client_and_persists(self):
        payloads = [
            make_api_payload(id=7100000000000000001, username="alice"),
            make_api_payload(id=7100000000000000002, username="bob", music_id=None),
        ]

        with patch(
            "ddcs.metadata.research_api.service.ResearchAPIClient"
        ) as client_cls:
            client_cls.return_value.query_videos_by_username.return_value = iter(
                payloads
            )
            service = ResearchAPIService()
            service.get_user_videos(["alice", "bob"], start_date="x", end_date="y")

            client_cls.return_value.query_videos_by_username.assert_called_once_with(
                ["alice", "bob"], start_date="x", end_date="y"
            )

        self.assertEqual(TikTokVideo.objects.count(), 2)
        self.assertEqual(
            set(TikTokUser.objects.values_list("name", flat=True)), {"alice", "bob"}
        )
        self.assertEqual(service.sync_stats["videos_created"], 2)
        self.assertEqual(service.sync_stats["users_created"], 2)
