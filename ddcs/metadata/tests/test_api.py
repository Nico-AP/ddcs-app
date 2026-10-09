from collections import defaultdict
from datetime import UTC, datetime, timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from ddcs.metadata.donations.models import DonationVideoInfos
from ddcs.metadata.donations.service import record_donated_videos
from ddcs.metadata.models import (
    Keyword,
    TikTokHashtag,
    TikTokMusic,
    TikTokUser,
    TikTokVideo,
    TikTokVideoClassification,
)
from ddcs.metadata.research_api.models import APIVideoInfos
from ddcs.metadata.research_api.service import ResearchAPIService
from ddcs.metadata.scraper.models import ScrapeTarget, VideoInfosScraped
from ddcs.metadata.scraper.service import ScraperService


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

    def _create_classification(self, video, **kwargs) -> TikTokVideoClassification:
        return TikTokVideoClassification.objects.create(video=video, **kwargs)

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

    def test_filter_by_create_date_range_to_only(self):
        video_out_of_range = self._create_video(111)
        self._create_api_info(
            video_out_of_range,
            create_time=timezone.datetime(
                2026, 6, 15, tzinfo=timezone.get_current_timezone()
            ),
        )

        video_in_range = self._create_video(222)
        self._create_api_info(
            video_in_range,
            create_time=timezone.datetime(
                2026, 1, 1, tzinfo=timezone.get_current_timezone()
            ),
        )

        response = self.client.get(
            self.url,
            {"create_date_to": "2026-02-01"},
        )

        ids = [v["id_tiktok"] for v in response.data["results"]]
        self.assertEqual(ids, [video_in_range.id_tiktok])

    def test_filter_create_date_excludes_video_without_api_info(self):
        _ = self._create_video(111)  # no _create_api_info call

        video_in_range = self._create_video(222)
        self._create_api_info(
            video_in_range,
            create_time=timezone.datetime(
                2026, 6, 15, tzinfo=timezone.get_current_timezone()
            ),
        )

        response = self.client.get(
            self.url, {"create_date_from": "2026-06-01", "create_date_to": "2026-06-30"}
        )

        ids = [v["id_tiktok"] for v in response.data["results"]]
        self.assertEqual(ids, [video_in_range.id_tiktok])

    def test_filter_create_date_from_after_to_returns_empty(self):
        video = self._create_video(111)
        self._create_api_info(
            video,
            create_time=timezone.datetime(
                2026, 6, 15, tzinfo=timezone.get_current_timezone()
            ),
        )

        response = self.client.get(
            self.url, {"create_date_from": "2026-07-01", "create_date_to": "2026-06-01"}
        )

        self.assertEqual(response.data["results"], [])

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

    # --- has classifications filter ---

    def test_filter_by_has_classifications(self):
        video = self._create_video(111)
        self._create_classification(video)

        video_no_classification = self._create_video(222)

        # case True
        response = self.client.get(self.url, {"has_classifications": True})
        ids = [v["id_tiktok"] for v in response.data["results"]]
        self.assertEqual(ids, [video.id_tiktok])

        # case False
        response = self.client.get(self.url, {"has_classifications": False})
        ids = [v["id_tiktok"] for v in response.data["results"]]
        self.assertEqual(ids, [video_no_classification.id_tiktok])

    # --- monitored users filter ---

    def test_filter_by_monitored_users(self):
        matching_user = TikTokUser.objects.create(
            name="alice", id_tiktok=10, monitor_api=True
        )
        other_user = TikTokUser.objects.create(
            name="bob", id_tiktok=20, monitor_api=False
        )
        matching_video = self._create_video(111, user=matching_user)
        self._create_video(222, user=other_user)

        response = self.client.get(self.url, {"monitored_users": True})

        ids = [v["id_tiktok"] for v in response.data["results"]]
        self.assertEqual(ids, [matching_video.id_tiktok])


class PrioritisedTikTokVideoListTestCase(APITestCase):
    def setUp(self):
        account = get_user_model().objects.create_user(username="zuse", password="x")
        self.token = Token.objects.create(user=account)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")
        self.url = reverse("metadata:tiktokvideo-prioritised-list")

        self.in_window = datetime(2026, 8, 5, 10, tzinfo=UTC)
        self.outside = datetime(2026, 10, 5, 10, tzinfo=UTC)

    def _video(  # noqa: PLR0913
        self,
        id_tiktok: int,
        *,
        api: bool = False,
        scraped: bool = False,
        seen: datetime | None = None,
        seen_in_window: datetime | None = None,
        donated: bool = False,
    ) -> TikTokVideo:
        video = TikTokVideo.objects.create(id_tiktok=id_tiktok)
        if api:
            APIVideoInfos.objects.create(
                video=video, description=f"api {id_tiktok}", region_code="CH"
            )
        if scraped:
            VideoInfosScraped.objects.create(
                video=video, description=f"scraped {id_tiktok}", raw={"big": "blob"}
            )
        if donated or seen or seen_in_window:
            DonationVideoInfos.objects.create(
                video=video,
                last_seen_at=seen or seen_in_window,
                last_seen_in_window_at=seen_in_window,
            )
        return video

    def _one_of_each(self) -> None:
        """One video per way of ending up with each priority."""
        self._video(41, api=True, seen_in_window=self.in_window)
        self._video(42, api=True, seen=self.outside)  # any donation counts
        self._video(43, api=True, donated=True)  # watched, date unknown
        self._video(31, seen_in_window=self.in_window)
        self._video(32, scraped=True, seen_in_window=self.in_window)
        self._video(21, api=True)
        self._video(22, api=True, scraped=True)
        self._video(11)
        self._video(12, seen=self.outside)  # donated, but outside the window
        self._video(13, scraped=True)

    def _get(self, **params: object) -> list[dict]:
        response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response.data["results"]

    def _ids(self, **params: object) -> set[int]:
        return {video["id_tiktok"] for video in self._get(**params)}

    def test_requires_authentication(self):
        self.client.credentials()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # --- Priority ---

    def test_priorities(self):
        self._one_of_each()

        priorities = {v["id_tiktok"]: v["priority"] for v in self._get()}

        self.assertEqual(
            priorities,
            {41: 4, 42: 4, 43: 4, 31: 3, 32: 3, 21: 2, 22: 2, 11: 1, 12: 1, 13: 1},
        )

    def test_filter_by_priority_matches_the_reported_priority(self):
        self._one_of_each()

        self.assertEqual(self._ids(priority="4"), {41, 42, 43})
        self.assertEqual(self._ids(priority="3"), {31, 32})
        self.assertEqual(self._ids(priority="2"), {21, 22})
        self.assertEqual(self._ids(priority="1"), {11, 12, 13})
        self.assertEqual(self._ids(priority="4,3"), {41, 42, 43, 31, 32})

    def test_unknown_priority_is_rejected(self):
        response = self.client.get(self.url, {"priority": "5"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_priority_rises_when_the_research_api_delivers_a_donated_video(self):
        video = self._video(1, seen_in_window=self.in_window)
        self.assertEqual(self._get()[0]["priority"], 3)

        APIVideoInfos.objects.create(video=video)

        self.assertEqual(self._get()[0]["priority"], 4)

    # --- Metadata and its source ---

    def test_research_api_metadata(self):
        user = TikTokUser.objects.create(name="alice")
        music = TikTokMusic.objects.create(id_tiktok=77)
        video = self._video(1, api=True, scraped=True, seen_in_window=self.in_window)
        video.user, video.music = user, music
        video.save()
        video.hashtags.add(TikTokHashtag.objects.create(name="wahl"))
        video.keywords.add(Keyword.objects.create(name="abstimmung"))

        result = self._get()[0]

        # The Research API wins over scraped data of the same video.
        self.assertEqual(result["metadata_source"], "research_api")
        self.assertEqual(result["description"], "api 1")
        self.assertEqual(result["region_code"], "CH")
        self.assertEqual(result["user"], "alice")
        self.assertEqual(result["music"], 77)
        self.assertEqual(result["hashtags"], ["wahl"])
        self.assertEqual(result["keywords"], ["abstimmung"])
        self.assertEqual(result["last_seen_at"], "2026-08-05T10:00:00Z")

    def test_scraped_metadata_is_served_when_there_is_no_research_api_data(self):
        video = self._video(1, seen_in_window=self.in_window)
        create_time = datetime(2026, 8, 1, 12, tzinfo=UTC)
        VideoInfosScraped.objects.create(video=video, description="old scrape")
        latest = VideoInfosScraped.objects.create(
            video=video,
            description="new scrape",
            create_time=create_time,
            duration=12,
            voice_to_text="hallo zusammen",
            video_mention_list=["bob"],
            caption_vtt="WEBVTT",
            raw={"big": "blob"},
        )
        VideoInfosScraped.objects.filter(pk=latest.pk).update(
            created_at=timezone.now() + timedelta(minutes=1)
        )

        result = self._get()[0]

        self.assertEqual(result["metadata_source"], "scraped")
        self.assertEqual(result["description"], "new scrape")
        self.assertEqual(result["create_time"], create_time.isoformat())
        self.assertEqual(result["duration"], 12)
        self.assertEqual(result["voice_to_text"], "hallo zusammen")
        self.assertEqual(result["video_mention_list"], ["bob"])
        # Research API only.
        self.assertIsNone(result["region_code"])
        self.assertIsNone(result["is_stem_verified"])
        self.assertIsNone(result["video_label"])
        self.assertNotIn("raw", result)
        self.assertNotIn("caption_vtt", result)

    def test_video_without_metadata(self):
        self._video(1)

        result = self._get()[0]

        self.assertEqual(result["id_tiktok"], 1)
        self.assertEqual(result["priority"], 1)
        self.assertIsNone(result["metadata_source"])
        self.assertIsNone(result["description"])
        self.assertIsNone(result["last_seen_at"])
        self.assertIsNone(result["user"])
        self.assertEqual(result["hashtags"], [])

    def test_filter_by_metadata_source(self):
        self._one_of_each()

        self.assertEqual(
            self._ids(metadata_source="research_api"), {41, 42, 43, 21, 22}
        )
        self.assertEqual(self._ids(metadata_source="scraped"), {32, 13})
        self.assertEqual(self._ids(has_metadata=True), {41, 42, 43, 21, 22, 32, 13})
        self.assertEqual(self._ids(has_metadata=False), {31, 11, 12})

    def test_filters_combine_with_those_of_the_video_list(self):
        self._one_of_each()

        self.assertEqual(self._ids(priority="4", id_tiktok="41,21"), {41})
        self.assertEqual(self._ids(priority="2", region_codes="CH"), {21, 22})

    # --- updated_since ---

    def test_updated_since_reports_what_changes_priority_or_metadata(self):
        self._one_of_each()
        TikTokVideo.objects.update(updated_at=timezone.now() - timedelta(days=2))
        since = (timezone.now() - timedelta(days=1)).isoformat()
        self.assertEqual(self._ids(updated_since=since), set())

        # Each through the code that does it in production: a donor saw
        # video 12 again, the Research API delivered video 31, and video 11
        # was scraped.
        record_donated_videos({12: timezone.now()}, {})
        api_service = ResearchAPIService.__new__(ResearchAPIService)
        api_service.sync_stats = defaultdict(int)
        api_service._sync_video({"id": 31}, None, None)
        ScraperService._store(
            ScrapeTarget.objects.create(video=TikTokVideo.objects.get(id_tiktok=11)),
            {"id": "11"},
            {},
        )

        self.assertEqual(self._ids(updated_since=since), {12, 31, 11})
        self.assertEqual(
            {v["id_tiktok"]: v["priority"] for v in self._get(updated_since=since)},
            {12: 1, 31: 4, 11: 1},
        )

    # --- Queries ---

    def test_number_of_queries_does_not_grow_with_the_page(self):
        def populate(first_id: int) -> None:
            for offset in range(3):
                video = self._video(
                    first_id + offset,
                    api=offset != 1,
                    scraped=True,
                    seen_in_window=self.in_window,
                )
                video.hashtags.add(
                    TikTokHashtag.objects.create(name=f"tag{first_id + offset}")
                )

        populate(100)
        with CaptureQueriesContext(connection) as few:
            self._get()

        populate(200)
        with CaptureQueriesContext(connection) as many:
            self.assertEqual(len(self._get()), 6)

        self.assertEqual(len(many), len(few))
