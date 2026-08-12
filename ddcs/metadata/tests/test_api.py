from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from ddcs.metadata.models import (
    Keyword,
    TikTokUser,
    TikTokVideo,
)
from ddcs.metadata.research_api.models import APIVideoInfos


class TikTokVideoListTestCase(APITestCase):
    def setUp(self):
        self.user_account = TikTokUser.objects.create(name="owner", id_tiktok=1)
        self.token = Token.objects.create(user=self._make_auth_user())
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

        # NOTE: adjust url name to match your actual urls.py registration
        self.url = reverse("metadata:tiktokvideo-list")

    def _make_auth_user(self):
        return get_user_model().objects.create_user(username="api_client", password="x")

    def _create_video(self, id_tiktok, **kwargs) -> TikTokVideo:
        return TikTokVideo.objects.create(id_tiktok=id_tiktok, **kwargs)

    def _create_api_info(self, video, created_at=None, **kwargs) -> APIVideoInfos:
        info = APIVideoInfos.objects.create(video=video, **kwargs)
        if created_at is not None:
            info.created_at = created_at
            info.save(update_fields=["created_at"])
        return info

    # --- Authentication ---

    def test_requires_authentication(self):
        self.client.credentials()  # remove token
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # --- Basic listing ---

    def test_list_returns_all_videos(self):
        self._create_video(111)
        self._create_video(222)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)

    def test_list_response_is_paginated(self):
        for i in range(3):
            self._create_video(1000 + i)

        response = self.client.get(self.url)

        self.assertIn("results", response.data)
        self.assertIn("next", response.data)
        self.assertIn("previous", response.data)

    # --- id_tiktok filter ---

    def test_filter_by_id_tiktok(self):
        v1 = self._create_video(111)
        self._create_video(222)

        response = self.client.get(self.url, {"id_tiktok": "111"})

        ids = [v["id_tiktok"] for v in response.data["results"]]
        self.assertEqual(ids, [v1.id_tiktok])

    def test_filter_by_id_tiktok_multiple(self):
        v1 = self._create_video(111)
        v2 = self._create_video(222)
        self._create_video(333)

        response = self.client.get(self.url, {"id_tiktok": "111,222"})

        ids = {v["id_tiktok"] for v in response.data["results"]}
        self.assertEqual(ids, {v1.id_tiktok, v2.id_tiktok})

    # --- usernames filter ---

    def test_filter_by_usernames(self):
        matching_user = TikTokUser.objects.create(name="alice", id_tiktok=10)
        other_user = TikTokUser.objects.create(name="bob", id_tiktok=20)
        matching_video = self._create_video(111, user=matching_user)
        self._create_video(222, user=other_user)

        response = self.client.get(self.url, {"usernames": "alice"})

        ids = [v["id_tiktok"] for v in response.data["results"]]
        self.assertEqual(ids, [matching_video.id_tiktok])

    # --- region_codes filter: MUST match latest api_infos row only ---

    def test_filter_by_region_codes_matches_only_latest_info(self):
        """
        A video with an OLD APIVideoInfos row matching region_code="US" but a
        NEWER row with a different region_code should NOT match ?region_codes=US,
        since the serializer only ever displays the latest row.
        """
        video = self._create_video(111)
        self._create_api_info(
            video,
            region_code="US",
            created_at=timezone.now() - timedelta(days=1),
        )
        self._create_api_info(
            video,
            region_code="DE",
            created_at=timezone.now(),
        )

        response = self.client.get(self.url, {"region_codes": "US"})

        self.assertEqual(response.data["results"], [])

    def test_filter_by_region_codes_matches_current_latest_info(self):
        video = self._create_video(111)
        self._create_api_info(
            video,
            region_code="US",
            created_at=timezone.now(),
        )

        response = self.client.get(self.url, {"region_codes": "US"})

        ids = [v["id_tiktok"] for v in response.data["results"]]
        self.assertEqual(ids, [video.id_tiktok])

    def test_filter_by_region_codes_excludes_video_with_no_api_info(self):
        self._create_video(111)  # no APIVideoInfos at all

        response = self.client.get(self.url, {"region_codes": "US"})

        self.assertEqual(response.data["results"], [])

    # --- create_date_from / create_date_to filters ---

    def test_filter_by_create_date_range(self):
        video_in_range = self._create_video(111)
        self._create_api_info(
            video_in_range,
            create_time=timezone.datetime(
                2026, 6, 15, tzinfo=timezone.get_current_timezone()
            ),
        )

        video_out_of_range = self._create_video(222)
        self._create_api_info(
            video_out_of_range,
            create_time=timezone.datetime(
                2026, 1, 1, tzinfo=timezone.get_current_timezone()
            ),
        )

        response = self.client.get(
            self.url,
            {"create_date_from": "2026-06-01", "create_date_to": "2026-06-30"},
        )

        ids = [v["id_tiktok"] for v in response.data["results"]]
        self.assertEqual(ids, [video_in_range.id_tiktok])

    # --- keywords filter (M2M on TikTokVideo) ---

    def test_filter_by_keywords(self):
        matching_keyword = Keyword.objects.create(name="brand_x")
        video_with_keyword = self._create_video(111)
        video_with_keyword.keywords.add(matching_keyword)

        self._create_video(222)  # no keywords

        response = self.client.get(self.url, {"keywords": "brand_x"})

        ids = [v["id_tiktok"] for v in response.data["results"]]
        self.assertEqual(ids, [video_with_keyword.id_tiktok])

    def test_filter_by_keywords_does_not_duplicate_results(self):
        """
        A video matching multiple requested keywords should appear once,
        not once per matching keyword (guards the .distinct() call).
        """
        kw1 = Keyword.objects.create(name="brand_x")
        kw2 = Keyword.objects.create(name="brand_y")
        video = self._create_video(111)
        video.keywords.set([kw1, kw2])

        response = self.client.get(self.url, {"keywords": "brand_x,brand_y"})

        self.assertEqual(len(response.data["results"]), 1)

    # --- updated_since filter ---

    def test_filter_by_updated_since_matches_recently_updated_video(self):
        cutoff = timezone.now()
        video = self._create_video(111)
        video.save()  # bumps auto_now updated_at past cutoff

        response = self.client.get(self.url, {"updated_since": cutoff.isoformat()})

        ids = [v["id_tiktok"] for v in response.data["results"]]
        self.assertEqual(ids, [video.id_tiktok])

    def test_filter_by_updated_since_matches_video_with_new_api_info(self):
        """
        A video whose own `updated_at` predates the cutoff, but which gained a
        NEW APIVideoInfos row after the cutoff, should still be considered
        "updated" for sync purposes.
        """
        video = self._create_video(111)
        cutoff = timezone.now() + timedelta(seconds=1)

        self._create_api_info(video, created_at=cutoff + timedelta(seconds=1))

        response = self.client.get(self.url, {"updated_since": cutoff.isoformat()})

        ids = [v["id_tiktok"] for v in response.data["results"]]
        self.assertEqual(ids, [video.id_tiktok])

    def test_filter_by_updated_since_excludes_untouched_video(self):
        self._create_video(111)
        future_cutoff = timezone.now() + timedelta(days=1)

        response = self.client.get(
            self.url, {"updated_since": future_cutoff.isoformat()}
        )

        self.assertEqual(response.data["results"], [])

    # --- has api infos filter ---

    def test_filter_by_has_api_infos(self):
        video = self._create_video(111)
        self._create_api_info(video, created_at=timezone.now())

        video_no_info = self._create_video(222)

        # case True
        response = self.client.get(self.url, {"has_api_infos": True})
        ids = [v["id_tiktok"] for v in response.data["results"]]
        self.assertEqual(ids, [video.id_tiktok])

        # case False
        response = self.client.get(self.url, {"has_api_infos": False})
        ids = [v["id_tiktok"] for v in response.data["results"]]
        self.assertEqual(ids, [video_no_info.id_tiktok])
