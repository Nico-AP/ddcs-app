from datetime import UTC, date, datetime
from unittest.mock import patch

from django.test import TestCase, override_settings

from ddcs.core.types import TikTokUserData
from ddcs.metadata.donations.models import DonationVideoInfos
from ddcs.metadata.donations.service import (
    record_donated_videos,
    register_donation_metadata,
    scan_watch_history,
)
from ddcs.metadata.models import DataOrigins, TikTokVideo
from ddcs.metadata.research_api.models import APIVideoInfos
from ddcs.metadata.scraper.models import ScrapeTarget


def _view(video_id: object, watched_at: object) -> dict:
    return {"video_id": video_id, "date": watched_at, "link": "https://example"}


class ScanWatchHistoryTests(TestCase):
    def test_window_includes_both_days_in_utc(self):
        history = [
            _view(1, datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)),  # day before
            _view(2, datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)),  # first moment
            _view(3, datetime(2026, 9, 20, 23, 59, 59, tzinfo=UTC)),  # last moment
            _view(4, datetime(2026, 9, 21, 0, 0, 0, tzinfo=UTC)),  # day after
        ]

        scan = scan_watch_history(history)

        self.assertEqual(set(scan.last_watched), {2, 3})
        self.assertEqual(scan.views_in_window, 2)
        self.assertEqual(scan.skipped_records, 0)

    def test_repeat_views_collapse_to_the_latest(self):
        early = datetime(2026, 7, 5, 10, tzinfo=UTC)
        late = datetime(2026, 8, 5, 10, tzinfo=UTC)

        scan = scan_watch_history([_view(1, late), _view(1, early), _view(1, late)])

        self.assertEqual(scan.last_watched, {1: late})
        self.assertEqual(scan.views_in_window, 3)

    def test_views_outside_the_window_do_not_set_the_last_view(self):
        inside = datetime(2026, 7, 5, 10, tzinfo=UTC)
        after = datetime(2026, 10, 1, 10, tzinfo=UTC)

        scan = scan_watch_history([_view(1, inside), _view(1, after)])

        self.assertEqual(scan.last_watched, {1: inside})

    def test_records_without_usable_date_or_video_id_are_skipped(self):
        inside = datetime(2026, 7, 5, 10, tzinfo=UTC)
        history = [
            _view(1, "05.07.2026 10:00"),  # date that could not be parsed
            _view(None, inside),  # link without an ID
            {"link": "https://example"},  # neither
            _view(2, inside),
        ]

        scan = scan_watch_history(history)

        self.assertEqual(scan.last_watched, {2: inside})
        self.assertEqual(scan.skipped_records, 3)

    def test_naive_dates_are_taken_as_utc(self):
        scan = scan_watch_history([_view(1, datetime(2026, 7, 1, 0, 0, 0))])  # noqa: DTZ001

        self.assertEqual(scan.last_watched, {1: datetime(2026, 7, 1, tzinfo=UTC)})

    def test_custom_window_and_empty_history(self):
        view = _view(1, datetime(2026, 1, 15, tzinfo=UTC))

        self.assertEqual(scan_watch_history([view]).last_watched, {})
        scan = scan_watch_history([view], start=date(2026, 1, 1), end=date(2026, 1, 31))
        self.assertEqual(set(scan.last_watched), {1})
        self.assertEqual(scan_watch_history(None).last_watched, {})

    def test_last_seen_covers_the_whole_history(self):
        inside = datetime(2026, 7, 5, 10, tzinfo=UTC)
        after = datetime(2026, 10, 1, 10, tzinfo=UTC)
        history = [
            _view(1, inside),
            _view(1, after),
            _view(2, after),
            _view(3, "05.07.2026 10:00"),  # date that could not be parsed
            _view(None, inside),
        ]

        scan = scan_watch_history(history)

        # Video 3 is in the history, even though it is not known when.
        self.assertEqual(scan.last_seen, {1: after, 2: after, 3: None})
        self.assertEqual(scan.last_watched, {1: inside})
        self.assertEqual(scan_watch_history(None).last_seen, {})


class RegisterDonationMetadataScrapeQueueTests(TestCase):
    def setUp(self):
        self.early = datetime(2026, 7, 5, 10, tzinfo=UTC)
        self.late = datetime(2026, 8, 5, 10, tzinfo=UTC)
        outside = datetime(2026, 10, 5, 10, tzinfo=UTC)
        self.data = TikTokUserData(
            watch_history=[
                {"video_id": 1, "date": self.early},
                {"video_id": 1, "date": self.late},
                {"video_id": 2, "date": self.early},
                {"video_id": 3, "date": outside},
            ],
            liked_videos=[{"video_id": 4, "date": self.early}],
        )

    def _ranking(self) -> dict[int, tuple]:
        return {
            id_tiktok: (count, last)
            for id_tiktok, count, last in ScrapeTarget.objects.values_list(
                "video__id_tiktok", "occurrence_count", "last_watched_at"
            )
        }

    @override_settings(TIKTOK_SCRAPER_ENABLED=False)
    def test_queues_nothing_while_scraper_is_disabled(self):
        register_donation_metadata(self.data)

        self.assertEqual(TikTokVideo.objects.count(), 4)
        self.assertFalse(ScrapeTarget.objects.exists())

    @override_settings(TIKTOK_SCRAPER_ENABLED=True)
    def test_queues_videos_watched_in_the_window_only(self):
        register_donation_metadata(self.data)

        # Not video 3 (watched outside the window), not video 4 (only liked).
        # Video 1 was watched twice by this donor: still one donation.
        self.assertEqual(self._ranking(), {1: (1, self.late), 2: (1, self.early)})

    @override_settings(TIKTOK_SCRAPER_ENABLED=True)
    def test_skips_videos_the_research_api_covers(self):
        covered = TikTokVideo.objects.create(
            id_tiktok=2, added_by=DataOrigins.RESEARCH_API
        )
        APIVideoInfos.objects.create(video=covered)

        register_donation_metadata(self.data)

        self.assertEqual(set(self._ranking()), {1})

    @override_settings(TIKTOK_SCRAPER_ENABLED=True)
    def test_another_donation_raises_the_count(self):
        register_donation_metadata(self.data)

        register_donation_metadata(
            TikTokUserData(watch_history=[{"video_id": 1, "date": self.early}])
        )

        self.assertEqual(self._ranking(), {1: (2, self.late), 2: (1, self.early)})


def _donated() -> dict[int, tuple]:
    return {
        id_tiktok: (seen, seen_in_window)
        for id_tiktok, seen, seen_in_window in DonationVideoInfos.objects.values_list(
            "video__id_tiktok", "last_seen_at", "last_seen_in_window_at"
        )
    }


class RecordDonationVideoInfossTests(TestCase):
    def setUp(self):
        self.early = datetime(2026, 7, 5, 10, tzinfo=UTC)
        self.late = datetime(2026, 8, 5, 10, tzinfo=UTC)
        self.outside = datetime(2026, 10, 5, 10, tzinfo=UTC)

    def test_creates_rows_and_missing_videos(self):
        TikTokVideo.objects.create(id_tiktok=1, added_by=DataOrigins.RESEARCH_API)

        result = record_donated_videos(
            {1: self.outside, 2: self.early, 3: None}, {2: self.early}
        )

        self.assertEqual((result.created, result.updated), (3, 0))
        self.assertEqual(
            _donated(),
            {1: (self.outside, None), 2: (self.early, self.early), 3: (None, None)},
        )
        # The origin of a video another source added first is left alone.
        self.assertEqual(
            dict(TikTokVideo.objects.values_list("id_tiktok", "added_by")),
            {
                1: DataOrigins.RESEARCH_API,
                2: DataOrigins.DONATION,
                3: DataOrigins.DONATION,
            },
        )

    def test_keeps_the_later_views(self):
        record_donated_videos({1: self.late, 2: self.early}, {1: self.late})

        result = record_donated_videos(
            {1: self.early, 2: self.outside, 3: self.early},
            {1: self.early, 2: self.early},
        )

        self.assertEqual((result.created, result.updated), (1, 1))
        self.assertEqual(
            _donated(),
            {
                1: (self.late, self.late),
                2: (self.outside, self.early),
                3: (self.early, None),
            },
        )

    def test_a_view_without_date_does_not_erase_a_known_one(self):
        record_donated_videos({1: self.early}, {1: self.early})

        result = record_donated_videos({1: None}, {})

        self.assertEqual(result.updated, 0)
        self.assertEqual(_donated(), {1: (self.early, self.early)})

    def test_marks_the_video_as_changed_only_when_a_view_moves(self):
        record_donated_videos({1: self.early, 2: self.early}, {})
        past = datetime(2026, 1, 1, tzinfo=UTC)
        TikTokVideo.objects.update(updated_at=past)
        DonationVideoInfos.objects.update(updated_at=past)

        record_donated_videos({1: self.early, 2: self.late, 3: self.early}, {})

        def changed(model: type, lookup: str) -> set[int]:
            return set(
                model.objects.filter(updated_at__gt=past).values_list(lookup, flat=True)
            )

        # Video 1 was seen no later than before; 2 was, 3 is new.
        self.assertEqual(changed(TikTokVideo, "id_tiktok"), {2, 3})
        self.assertEqual(changed(DonationVideoInfos, "video__id_tiktok"), {2, 3})

    def test_marks_a_video_another_source_registered_as_changed(self):
        past = datetime(2026, 1, 1, tzinfo=UTC)
        TikTokVideo.objects.create(id_tiktok=1, added_by=DataOrigins.RESEARCH_API)
        TikTokVideo.objects.update(updated_at=past)

        record_donated_videos({1: self.early}, {})

        self.assertGreater(TikTokVideo.objects.get().updated_at, past)

    def test_works_in_chunks(self):
        with patch("ddcs.metadata.donations.service._RECORD_CHUNK_SIZE", 2):
            result = record_donated_videos(dict.fromkeys(range(1, 6), self.early), {})

        self.assertEqual(result.created, 5)
        self.assertEqual(DonationVideoInfos.objects.count(), 5)


class RegisterDonationMetadataDonationVideoInfossTests(TestCase):
    def setUp(self):
        self.inside = datetime(2026, 7, 5, 10, tzinfo=UTC)
        self.outside = datetime(2026, 10, 5, 10, tzinfo=UTC)
        self.data = TikTokUserData(
            watch_history=[
                {"video_id": 1, "date": self.inside},
                {"video_id": 1, "date": self.outside},
                {"video_id": 2, "date": self.outside},
            ],
            liked_videos=[{"video_id": 3, "date": self.inside}],
        )

    @override_settings(TIKTOK_SCRAPER_ENABLED=False)
    def test_records_watched_videos_while_scraper_is_disabled(self):
        register_donation_metadata(self.data)

        # Not video 3: it was only liked.
        self.assertEqual(
            _donated(), {1: (self.outside, self.inside), 2: (self.outside, None)}
        )

    @override_settings(TIKTOK_SCRAPER_ENABLED=True)
    def test_records_videos_the_research_api_covers(self):
        covered = TikTokVideo.objects.create(
            id_tiktok=1, added_by=DataOrigins.RESEARCH_API
        )
        APIVideoInfos.objects.create(video=covered)

        register_donation_metadata(self.data)

        self.assertIn(1, _donated())
        self.assertFalse(ScrapeTarget.objects.filter(video=covered).exists())

    def test_donation_without_watch_history(self):
        register_donation_metadata(TikTokUserData(liked_videos=self.data.liked_videos))

        self.assertFalse(DonationVideoInfos.objects.exists())
