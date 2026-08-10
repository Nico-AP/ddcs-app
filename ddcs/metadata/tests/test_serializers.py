from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from ddcs.metadata.models import (
    Keyword,
    TikTokHashtag,
    TikTokMusic,
    TikTokUser,
    TikTokVideo,
)
from ddcs.metadata.research_api.models import APIVideoInfos
from ddcs.metadata.serializers import TikTokVideoSerializer


class TikTokVideoSerializerTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.request = self.factory.get("/")

        self.user = TikTokUser.objects.create(name="user", id_tiktok=111)
        self.music = TikTokMusic.objects.create(id_tiktok=222)
        self.hashtag1 = TikTokHashtag.objects.create(name="funny")
        self.hashtag2 = TikTokHashtag.objects.create(name="kokolores")
        self.keyword1 = Keyword.objects.create(name="kokolores")

        self.video = TikTokVideo.objects.create(
            id_tiktok=333,
            user=self.user,
            music=self.music,
        )
        self.video.hashtags.set([self.hashtag1, self.hashtag2])
        self.video.keywords.set([self.keyword1])

    def _serialize(self, obj):
        return TikTokVideoSerializer(obj, context={"request": self.request}).data

    def test_video_without_api_info_returns_none_fields(self):
        data = self._serialize(self.video)

        self.assertEqual(data["id_tiktok"], 333)
        self.assertEqual(data["user"], "user")
        self.assertEqual(data["music"], 222)
        self.assertCountEqual(data["hashtags"], ["funny", "kokolores"])
        self.assertCountEqual(data["keywords"], ["kokolores"])

        # No APIVideoInfos exist yet -> all method fields should be None
        self.assertIsNone(data["description"])
        self.assertIsNone(data["region_code"])
        self.assertIsNone(data["duration"])
        self.assertIsNone(data["voice_to_text"])
        self.assertIsNone(data["is_stem_verified"])
        self.assertIsNone(data["video_mention_list"])
        self.assertIsNone(data["video_label"])
        self.assertIsNone(data["effect_list"])

    def test_video_with_single_api_info(self):
        APIVideoInfos.objects.create(
            video=self.video,
            description="A cool video",
            region_code="CH",
            duration=15,
            voice_to_text="hello world",
            is_stem_verified=True,
            video_mention_list=["@a", "@b"],
            video_label={"label": "kokolores"},
            effect_list=["sparkle"],
        )

        data = self._serialize(self.video)

        self.assertEqual(data["description"], "A cool video")
        self.assertEqual(data["region_code"], "CH")
        self.assertEqual(data["duration"], 15)
        self.assertEqual(data["voice_to_text"], "hello world")
        self.assertTrue(data["is_stem_verified"])
        self.assertEqual(data["video_mention_list"], ["@a", "@b"])
        self.assertEqual(data["video_label"], {"label": "kokolores"})
        self.assertEqual(data["effect_list"], ["sparkle"])

    def test_uses_latest_api_info_by_created_at(self):
        older = APIVideoInfos.objects.create(
            video=self.video,
            description="Old description",
        )
        # Force created_at ordering explicitly in case auto_now_add makes
        # them too close together / equal in a fast test run.
        older.created_at = timezone.now() - timedelta(days=1)
        older.save(update_fields=["created_at"])

        newer = APIVideoInfos.objects.create(
            video=self.video,
            description="New description",
        )
        newer.created_at = timezone.now()
        newer.save(update_fields=["created_at"])

        data = self._serialize(self.video)

        self.assertEqual(data["description"], "New description")

    def test_prefetched_latest_api_info_list_is_used_when_present(self):
        api_info = APIVideoInfos.objects.create(
            video=self.video,
            description="From prefetch list",
        )
        # Simulate a view that annotates a single-item list of the latest
        # api info to avoid an extra query per instance.
        self.video.latest_api_info_list = [api_info]

        data = self._serialize(self.video)

        self.assertEqual(data["description"], "From prefetch list")

    def test_prefetched_latest_api_info_list_empty(self):
        # Prefetch attribute exists but is empty -> should behave like "no api info"
        self.video.latest_api_info_list = []

        data = self._serialize(self.video)

        self.assertIsNone(data["description"])
        self.assertIsNone(data["duration"])

    def test_video_without_user_returns_none(self):
        self.video.user = None
        self.video.save()

        data = self._serialize(self.video)

        self.assertIsNone(data["user"])

    def test_video_without_music_returns_none(self):
        self.video.music = None
        self.video.save()

        data = self._serialize(self.video)

        self.assertIsNone(data["music"])

    def test_video_without_hashtags_returns_empty_list(self):
        self.video.hashtags.clear()

        data = self._serialize(self.video)

        self.assertEqual(data["hashtags"], [])

    def test_hashtags_are_writable_by_slug(self):
        _ = TikTokHashtag.objects.create(name="new_tag")
        serializer = TikTokVideoSerializer(
            self.video,
            data={
                "id_tiktok": self.video.id_tiktok,
                "hashtags": ["new_tag"],
            },
            partial=True,
            context={"request": self.request},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()

        self.video.refresh_from_db()
        self.assertEqual(
            list(self.video.hashtags.values_list("name", flat=True)),
            ["new_tag"],
        )
