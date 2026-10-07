from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from ddcs.metadata.research_api.models import APIVideoInfos
from ddcs.metadata.scraper.config import PRIORITY_MIN_OCCURRENCES
from ddcs.metadata.scraper.exceptions import TikTokBlockedError
from ddcs.metadata.scraper.models import (
    ScrapeTarget,
    VideoInfosScraped,
    VideoStatisticsScraped,
)
from ddcs.metadata.scraper.service import INTERNAL_SCRAPER_LABEL
from ddcs.metadata.scraper.test_service import (
    _PAYLOAD,
    _VTT,
    _WATCHED_AT,
    _error,
    _service,
    _success,
    _target,
    _video,
)

Status = ScrapeTarget.Status
CaptionStatus = VideoInfosScraped.CaptionStatus

_ID = int(_PAYLOAD["id"])


class ExternalScraperAPITestCase(APITestCase):
    def setUp(self):
        self.claim_url = reverse("metadata:scrapetarget-claim")
        self.results_url = reverse("metadata:scrapetarget-results")
        self.scraper = self._make_scraper("scraper_a")
        self._authenticate(self.scraper)

    def _make_scraper(self, username: str, *, permitted: bool = True):
        user = get_user_model().objects.create_user(username=username, password="x")
        if permitted:
            user.user_permissions.add(
                Permission.objects.get(codename="sync_scrape_targets")
            )
        Token.objects.create(user=user)
        return user

    def _authenticate(self, user) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {user.auth_token.key}")

    def _claim(self, **data) -> list[int]:
        response = self.client.post(self.claim_url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return [row["id_tiktok"] for row in response.data["results"]]

    def _submit(self, *results: object) -> list[dict]:
        response = self.client.post(
            self.results_url, {"results": list(results)}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.data["results"]


class AccessTests(ExternalScraperAPITestCase):
    def test_requires_authentication(self):
        self.client.credentials()
        for url in (self.claim_url, self.results_url):
            response = self.client.post(url, {}, format="json")
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_requires_the_sync_permission(self):
        _target(_video(1))
        self._authenticate(self._make_scraper("reader", permitted=False))
        for url in (self.claim_url, self.results_url):
            response = self.client.post(url, {}, format="json")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIsNone(ScrapeTarget.objects.get().claimed_until)


class ClaimTests(ExternalScraperAPITestCase):
    def test_claim_returns_targets_in_queue_order_and_leases_them(self):
        late = _WATCHED_AT + timedelta(days=3)
        _target(_video(1), occurrence_count=1, last_watched_at=_WATCHED_AT)
        _target(_video(2), occurrence_count=1, last_watched_at=late)
        _target(
            _video(3),
            occurrence_count=PRIORITY_MIN_OCCURRENCES,
            last_watched_at=_WATCHED_AT,
        )

        response = self.client.post(
            self.claim_url, {"scraper_id": "host-1"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["results"][0],
            {
                "id_tiktok": 3,
                "occurrence_count": PRIORITY_MIN_OCCURRENCES,
                "last_watched_at": "2026-08-01T12:00:00Z",
            },
        )
        self.assertEqual([r["id_tiktok"] for r in response.data["results"]], [3, 2, 1])
        for target in ScrapeTarget.objects.all():
            self.assertEqual(target.claimed_by, self.scraper)
            self.assertEqual(target.claimed_by_label, "host-1")
            self.assertEqual(target.claimed_until, response.data["lease_expires_at"])
            self.assertEqual((target.status, target.attempts), (Status.PENDING, 0))

    @override_settings(TIKTOK_SCRAPER_EXTERNAL_LEASE_MINUTES=10)
    def test_lease_length_follows_the_setting(self):
        _target(_video(1))
        before = timezone.now()

        self._claim()

        lease = ScrapeTarget.objects.get().claimed_until - before
        self.assertAlmostEqual(lease.total_seconds(), 600, delta=5)

    def test_limit_is_respected_and_validated(self):
        for i in range(1, 4):
            _target(_video(i), last_watched_at=_WATCHED_AT - timedelta(days=i))

        self.assertEqual(self._claim(limit=2), [1, 2])
        for limit in (0, 501):
            response = self.client.post(self.claim_url, {"limit": limit}, format="json")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_claimed_targets_are_not_handed_out_twice(self):
        for i in range(1, 4):
            _target(_video(i), last_watched_at=_WATCHED_AT - timedelta(days=i))

        first = self._claim(limit=2)
        self._authenticate(self._make_scraper("scraper_b"))
        second = self._claim(limit=2)

        self.assertEqual((first, second), ([1, 2], [3]))
        self.assertEqual(self._claim(), [])

    def test_expired_lease_is_handed_out_again(self):
        target = _target(_video(1))
        self._claim()
        ScrapeTarget.objects.update(claimed_until=timezone.now() - timedelta(seconds=1))
        other = self._make_scraper("scraper_b")
        self._authenticate(other)

        self.assertEqual(self._claim(), [1])
        target.refresh_from_db()
        self.assertEqual(target.claimed_by, other)

    def test_only_due_targets_are_handed_out(self):
        _target(_video(1), status=Status.SUCCESS, attempts=1)
        _target(_video(2), status=Status.UNAVAILABLE, attempts=1)
        # Failed a moment ago: not due before the backoff has passed.
        _target(
            _video(3),
            status=Status.FAILED,
            attempts=1,
            last_attempted_at=timezone.now(),
        )
        covered = _video(4)
        APIVideoInfos.objects.create(video=covered)
        _target(covered)
        _target(_video(5))

        self.assertEqual(self._claim(), [5])
        self.assertEqual(
            ScrapeTarget.objects.get(video=covered).status, Status.COVERED_BY_API
        )

    def test_internal_scraper_skips_externally_claimed_targets(self):
        _target(_video(1), last_watched_at=_WATCHED_AT)
        _target(_video(2), last_watched_at=_WATCHED_AT - timedelta(days=1))
        self._claim(limit=1)
        service, scraper = _service(_success())

        service.scrape_batch(limit=10)

        scraper.scrape_video_list.assert_called_once_with(["2"])

    def test_targets_the_internal_scraper_holds_are_not_handed_out(self):
        _target(
            _video(1),
            claimed_by_label=INTERNAL_SCRAPER_LABEL,
            claimed_until=timezone.now() + timedelta(minutes=30),
        )

        self.assertEqual(self._claim(), [])


class ResultsTests(ExternalScraperAPITestCase):
    def setUp(self):
        super().setUp()
        self.video = _video(_ID)
        self.target = _target(self.video)

    def _claimed(self) -> None:
        self.assertEqual(self._claim(scraper_id="host-1"), [_ID])

    def _reload(self) -> ScrapeTarget:
        self.target.refresh_from_db()
        return self.target

    def test_success_stores_data_and_finishes_the_target(self):
        self._claimed()

        results = self._submit(
            {"id_tiktok": _ID, "outcome": "success", "data": _PAYLOAD}
        )

        self.assertEqual(
            results, [{"id_tiktok": _ID, "status": "stored", "detail": ""}]
        )
        infos = VideoInfosScraped.objects.get(video=self.video)
        self.assertEqual(infos.description, "a description #tag")
        self.assertEqual(infos.caption_status, CaptionStatus.NOT_REQUESTED)
        self.assertNotIn("playAddr", infos.raw["video"])
        self.assertEqual(
            VideoStatisticsScraped.objects.get(video=self.video).view_count, 514600
        )
        self.video.refresh_from_db()
        self.assertIsNotNone(self.video.scraped_at)
        self.assertEqual(self.video.user.name, "scraped_author")
        target = self._reload()
        self.assertEqual((target.status, target.attempts), (Status.SUCCESS, 1))
        # The lease is over; who scraped the video stays on record.
        self.assertIsNone(target.claimed_until)
        self.assertEqual(target.claimed_by, self.scraper)
        self.assertEqual(target.claimed_by_label, "host-1")

    def test_success_with_caption(self):
        self._claimed()

        self._submit(
            {
                "id_tiktok": _ID,
                "outcome": "success",
                "data": _PAYLOAD,
                "caption": {
                    "status": "fetched",
                    "vtt": _VTT,
                    "language": "deu-DE",
                    "is_auto_generated": False,
                },
            }
        )

        infos = VideoInfosScraped.objects.get()
        self.assertEqual(infos.caption_status, CaptionStatus.FETCHED)
        self.assertEqual(infos.voice_to_text, "Hallo zusammen")
        self.assertEqual(infos.caption_vtt, _VTT)
        self.assertEqual(infos.caption_language, "deu-DE")
        self.assertIs(infos.caption_is_auto_generated, False)

    def test_success_without_available_caption(self):
        self._claimed()

        self._submit(
            {
                "id_tiktok": _ID,
                "outcome": "success",
                "data": _PAYLOAD,
                "caption": {"status": "none_available"},
            }
        )

        infos = VideoInfosScraped.objects.get()
        self.assertEqual(infos.caption_status, CaptionStatus.NONE_AVAILABLE)
        self.assertEqual(infos.voice_to_text, "")

    def test_unavailable_is_final(self):
        self._claimed()

        results = self._submit(
            {"id_tiktok": _ID, "outcome": "unavailable", "tiktok_status_code": 10204}
        )

        self.assertEqual(results[0]["status"], "recorded")
        target = self._reload()
        self.assertEqual(target.status, Status.UNAVAILABLE)
        self.assertEqual(target.tiktok_status_code, 10204)
        self.assertEqual(target.last_error_type, "TikTokItemUnavailableError")
        self.assertIsNone(target.claimed_until)

    def test_failed_counts_an_attempt_and_waits_for_backoff(self):
        self._claimed()

        results = self._submit(
            {
                "id_tiktok": _ID,
                "outcome": "failed",
                "error_type": "ParseError",
                "error_msg": "no rehydration data",
            }
        )

        self.assertEqual(results[0]["status"], "recorded")
        target = self._reload()
        self.assertEqual((target.status, target.attempts), (Status.FAILED, 1))
        self.assertEqual(target.last_error_type, "ParseError")
        self.assertEqual(target.last_error_msg, "no rehydration data")
        self.assertEqual(self._claim(), [])

    def test_released_returns_the_target_without_an_attempt(self):
        self._claimed()

        results = self._submit({"id_tiktok": _ID, "outcome": "released"})

        self.assertEqual(results[0]["status"], "released")
        target = self._reload()
        self.assertEqual((target.status, target.attempts), (Status.PENDING, 0))
        self.assertEqual(self._claim(), [_ID])

    def test_result_for_unclaimed_target_is_rejected(self):
        results = self._submit(
            {"id_tiktok": _ID, "outcome": "success", "data": _PAYLOAD},
            {"id_tiktok": 999, "outcome": "released"},
        )

        self.assertEqual([r["status"] for r in results], ["not_claimed"] * 2)
        self.assertFalse(VideoInfosScraped.objects.exists())
        self.assertEqual(self._reload().status, Status.PENDING)

    def test_result_for_another_scrapers_target_is_rejected(self):
        self._claimed()
        self._authenticate(self._make_scraper("scraper_b"))

        results = self._submit(
            {"id_tiktok": _ID, "outcome": "unavailable", "tiktok_status_code": 10204}
        )

        self.assertEqual(results[0]["status"], "not_claimed")
        self.assertEqual(self._reload().status, Status.PENDING)

    def test_result_after_lease_expired_is_still_accepted(self):
        self._claimed()
        ScrapeTarget.objects.update(claimed_until=timezone.now() - timedelta(minutes=1))

        results = self._submit(
            {"id_tiktok": _ID, "outcome": "success", "data": _PAYLOAD}
        )

        self.assertEqual(results[0]["status"], "stored")

    def test_resubmitting_a_finished_target_changes_nothing(self):
        self._claimed()
        item = {"id_tiktok": _ID, "outcome": "success", "data": _PAYLOAD}
        self._submit(item)

        results = self._submit(item)

        self.assertEqual(results[0]["status"], "already_done")
        self.assertEqual(VideoInfosScraped.objects.count(), 1)
        self.assertEqual(self._reload().attempts, 1)

    def test_data_of_another_video_is_refused_and_leaves_the_target_alone(self):
        self._claimed()

        results = self._submit(
            {"id_tiktok": _ID, "outcome": "success", "data": {**_PAYLOAD, "id": "5"}}
        )

        self.assertEqual(results[0]["status"], "invalid")
        self.assertFalse(VideoInfosScraped.objects.exists())
        target = self._reload()
        self.assertEqual((target.status, target.attempts), (Status.PENDING, 0))
        self.assertIsNotNone(target.claimed_until)

    def test_data_that_cannot_be_stored_marks_the_target_failed(self):
        self._claimed()

        results = self._submit(
            {
                "id_tiktok": _ID,
                "outcome": "success",
                # Not the structure the counts are read from.
                "data": {**_PAYLOAD, "stats": "broken", "statsV2": None},
            }
        )

        self.assertEqual(results[0]["status"], "invalid")
        self.assertFalse(VideoInfosScraped.objects.exists())
        self.assertEqual(self._reload().status, Status.FAILED)

    def test_entries_are_handled_independently(self):
        other = _target(_video(2))
        self.assertEqual(len(self._claim()), 2)

        results = self._submit(
            {"id_tiktok": _ID, "outcome": "success"},  # no data
            "not an object",
            {"id_tiktok": _ID, "outcome": "success", "data": _PAYLOAD},
            {"id_tiktok": 2, "outcome": "released"},
        )

        self.assertEqual(
            [(r["id_tiktok"], r["status"]) for r in results],
            [(_ID, "invalid"), (None, "invalid"), (_ID, "stored"), (2, "released")],
        )
        self.assertIn("data", results[0]["detail"])
        other.refresh_from_db()
        self.assertIsNone(other.claimed_until)

    def test_fetched_caption_needs_the_file(self):
        self._claimed()

        results = self._submit(
            {
                "id_tiktok": _ID,
                "outcome": "success",
                "data": _PAYLOAD,
                "caption": {"status": "fetched"},
            }
        )

        self.assertEqual(results[0]["status"], "invalid")
        self.assertIn("vtt", results[0]["detail"])

    def test_envelope_is_validated(self):
        item = {"id_tiktok": _ID, "outcome": "released"}
        for body in ({}, {"results": []}, {"results": [item] * 51}):
            response = self.client.post(self.results_url, body, format="json")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class SchemaTests(APITestCase):
    def test_endpoints_are_part_of_the_api_schema(self):
        response = self.client.get(reverse("schema"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        paths = response.data["paths"]
        self.assertIn("/metadata/api/v1/tiktok/scrape-targets/claim/", paths)
        self.assertIn("/metadata/api/v1/tiktok/scrape-targets/results/", paths)


class InternalLeaseTests(APITestCase):
    """The built-in scraper leases its batch like an external one does."""

    def test_batch_is_leased_while_it_runs_and_free_again_afterwards(self):
        for i in range(1, 4):
            _target(_video(i), last_watched_at=_WATCHED_AT - timedelta(days=i))
        blocked = _error(TikTokBlockedError("blocked"))
        results = [_success({**_PAYLOAD, "id": "1"}), blocked, blocked]
        service, scraper = _service()
        leased_during_batch = []

        def scrape(ids: list[str]):
            leased_during_batch.append(
                ScrapeTarget.objects.filter(
                    claimed_until__gt=timezone.now(),
                    claimed_by_label=INTERNAL_SCRAPER_LABEL,
                ).count()
            )
            return iter(results)

        scraper.scrape_video_list.side_effect = scrape

        service.scrape_batch(limit=10)

        self.assertEqual(leased_during_batch, [3])
        # Neither the scraped video nor the two blocked ones stay leased.
        self.assertFalse(ScrapeTarget.objects.filter(claimed_until__isnull=False))
        self.assertEqual(ScrapeTarget.objects.filter(status=Status.PENDING).count(), 2)
