from datetime import UTC, date, datetime
from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from ddcs.core.types import TikTokUserData
from ddcs.metadata.donations.config import EXCLUDED_PARTICIPANT_IDS
from ddcs.metadata.donations.models import DonationVideoInfos
from ddcs.metadata.donations.service import (
    VideoInteractions,
    queue_entries,
    record_donated_videos,
    register_donation_metadata,
    reset_donation_counts,
    scan_donated_videos,
)
from ddcs.metadata.models import DataOrigins, TikTokVideo
from ddcs.metadata.research_api.models import APIVideoInfos
from ddcs.metadata.scraper.models import ScrapeTarget
from ddcs.metadata.scraper.service import enqueue_donated_videos


def _view(video_id: object, watched_at: object) -> dict:
    return {"video_id": video_id, "date": watched_at, "link": "https://example"}


EARLY = datetime(2026, 7, 5, 10, tzinfo=UTC)
LATE = datetime(2026, 8, 5, 10, tzinfo=UTC)
OUTSIDE = datetime(2026, 10, 5, 10, tzinfo=UTC)


def _seen(
    kinds: str = "w",
    last: datetime | None = None,
    last_in_window: datetime | None = None,
) -> VideoInteractions:
    """Interactions of one donation: ``kinds`` out of w(atched), l(iked),
    b(ookmarked)."""
    return VideoInteractions(
        "w" in kinds, "l" in kinds, "b" in kinds, last, last_in_window
    )


def _counts() -> dict[int, tuple[int, int, int]]:
    """TikTok ID -> (watched, liked, bookmarked) counts."""
    return {
        id_tiktok: tuple(counts)
        for id_tiktok, *counts in DonationVideoInfos.objects.values_list(
            "video__id_tiktok", "watched_count", "liked_count", "bookmarked_count"
        )
    }


def _interactions() -> dict[int, tuple]:
    """TikTok ID -> (last interaction, last interaction in the window)."""
    return {
        id_tiktok: tuple(times)
        for id_tiktok, *times in DonationVideoInfos.objects.values_list(
            "video__id_tiktok", "last_interaction_at", "last_interaction_in_window_at"
        )
    }


def _ranking() -> dict[int, tuple[int, datetime | None]]:
    """TikTok ID -> (donor count, most recent interaction) of the scrape targets."""
    return {
        id_tiktok: (count, last)
        for id_tiktok, count, last in ScrapeTarget.objects.values_list(
            "video__id_tiktok", "occurrence_count", "last_watched_at"
        )
    }


def _changed_since(model: type, lookup: str, moment: datetime) -> set[int]:
    return set(
        model.objects.filter(updated_at__gt=moment).values_list(lookup, flat=True)
    )


class ScanDonatedVideosTests(TestCase):
    def test_finds_watched_liked_and_bookmarked_videos(self):
        data = TikTokUserData(
            watch_history=[_view(1, EARLY), _view(2, EARLY)],
            liked_videos=[_view(2, LATE), _view(3, EARLY)],
            video_bookmarks=[_view(3, LATE), _view(4, OUTSIDE)],
        )

        self.assertEqual(
            scan_donated_videos(data),
            {
                1: _seen("w", EARLY, EARLY),
                # The most recent interaction, whichever kind it was.
                2: _seen("wl", LATE, LATE),
                3: _seen("lb", LATE, LATE),
                4: _seen("b", OUTSIDE, None),
            },
        )

    def test_window_applies_to_every_kind_of_interaction(self):
        data = TikTokUserData(
            watch_history=[_view(1, OUTSIDE)],
            liked_videos=[_view(1, EARLY)],
        )

        # Watched after the window, but liked within it.
        self.assertEqual(scan_donated_videos(data), {1: _seen("wl", OUTSIDE, EARLY)})

    def test_window_includes_both_days_in_utc(self):
        data = TikTokUserData(
            liked_videos=[
                _view(1, datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)),
                _view(2, datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)),
                _view(3, datetime(2026, 9, 20, 23, 59, 59, tzinfo=UTC)),
                _view(4, datetime(2026, 9, 21, 0, 0, 0, tzinfo=UTC)),
            ]
        )

        in_window = {
            video_id
            for video_id, video in scan_donated_videos(data).items()
            if video.last_interaction_in_window_at
        }
        self.assertEqual(in_window, {2, 3})

    def test_repeat_views_are_one_interaction_with_the_latest_date(self):
        data = TikTokUserData(
            watch_history=[_view(1, LATE), _view(1, EARLY), _view(1, LATE)]
        )

        self.assertEqual(scan_donated_videos(data), {1: _seen("w", LATE, LATE)})

    def test_record_without_usable_date_still_counts(self):
        data = TikTokUserData(
            watch_history=[_view(1, "05.07.2026 10:00")],
            video_bookmarks=[
                _view(2, "05.07.2026 10:00"),
                _view(2, EARLY),
                _view(None, EARLY),  # link without an ID
                {"date": EARLY},
            ],
        )

        self.assertEqual(
            scan_donated_videos(data),
            {1: _seen("w", None, None), 2: _seen("b", EARLY, EARLY)},
        )

    def test_naive_dates_are_taken_as_utc(self):
        data = TikTokUserData(
            liked_videos=[_view(1, datetime(2026, 7, 1, 0, 0, 0))]  # noqa: DTZ001
        )

        at = datetime(2026, 7, 1, tzinfo=UTC)
        self.assertEqual(scan_donated_videos(data), {1: _seen("l", at, at)})

    def test_custom_window_and_empty_donation(self):
        data = TikTokUserData(liked_videos=[_view(1, OUTSIDE)])

        scan = scan_donated_videos(
            data, start=date(2026, 10, 1), end=date(2026, 10, 31)
        )

        self.assertEqual(scan, {1: _seen("l", OUTSIDE, OUTSIDE)})
        self.assertEqual(scan_donated_videos(TikTokUserData()), {})


class QueueEntriesTests(TestCase):
    def test_videos_with_an_interaction_in_the_window(self):
        videos = {
            1: _seen("w", LATE, LATE),
            2: _seen("l", OUTSIDE, EARLY),  # liked in the window, seen after it
            3: _seen("b", OUTSIDE, None),
            4: _seen("w"),
        }

        self.assertEqual(queue_entries(videos), {1: (1, LATE), 2: (1, EARLY)})
        self.assertEqual(queue_entries({}), {})


class RegisterDonationMetadataScrapeQueueTests(TestCase):
    def setUp(self):
        self.data = TikTokUserData(
            watch_history=[
                {"video_id": 1, "date": EARLY},
                {"video_id": 1, "date": LATE},
                {"video_id": 2, "date": EARLY},
                {"video_id": 3, "date": OUTSIDE},
            ],
            liked_videos=[
                {"video_id": 3, "date": LATE},
                {"video_id": 4, "date": EARLY},
            ],
            video_bookmarks=[
                {"video_id": 5, "date": LATE},
                {"video_id": 6, "date": OUTSIDE},
            ],
            shared_videos=[{"video_id": 7, "date": EARLY}],
        )

    @override_settings(TIKTOK_SCRAPER_ENABLED=False)
    def test_queues_nothing_while_scraper_is_disabled(self):
        register_donation_metadata(self.data)

        self.assertTrue(DonationVideoInfos.objects.exists())
        self.assertFalse(ScrapeTarget.objects.exists())

    @override_settings(TIKTOK_SCRAPER_ENABLED=True)
    def test_queues_videos_with_an_interaction_in_the_window(self):
        register_donation_metadata(self.data)

        self.assertEqual(
            _ranking(),
            {
                # Watched twice by this donor: still one donation.
                1: (1, LATE),
                2: (1, EARLY),
                # Watched after the window, but liked within it.
                3: (1, LATE),
                4: (1, EARLY),
                5: (1, LATE),
                # Not video 6 (bookmarked outside the window), not video 7
                # (only shared).
            },
        )

    @override_settings(TIKTOK_SCRAPER_ENABLED=True)
    def test_skips_videos_the_research_api_covers(self):
        covered = TikTokVideo.objects.create(
            id_tiktok=2, added_by=DataOrigins.RESEARCH_API
        )
        APIVideoInfos.objects.create(video=covered)

        register_donation_metadata(self.data)

        self.assertEqual(set(_ranking()), {1, 3, 4, 5})

    @override_settings(TIKTOK_SCRAPER_ENABLED=True)
    def test_another_donation_raises_the_count(self):
        register_donation_metadata(self.data)

        register_donation_metadata(
            TikTokUserData(video_bookmarks=[{"video_id": 1, "date": EARLY}])
        )

        self.assertEqual(_ranking()[1], (2, LATE))
        self.assertEqual(_ranking()[2], (1, EARLY))


class RecordDonatedVideosTests(TestCase):
    def test_creates_rows_and_missing_videos(self):
        TikTokVideo.objects.create(id_tiktok=1, added_by=DataOrigins.RESEARCH_API)

        result = record_donated_videos(
            {
                1: _seen("w", OUTSIDE),
                2: _seen("wl", EARLY, EARLY),
                3: _seen("b"),
            }
        )

        self.assertEqual((result.created, result.updated), (3, 0))
        self.assertEqual(_counts(), {1: (1, 0, 0), 2: (1, 1, 0), 3: (0, 0, 1)})
        self.assertEqual(
            _interactions(), {1: (OUTSIDE, None), 2: (EARLY, EARLY), 3: (None, None)}
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

    def test_another_donation_raises_the_counts_it_shows(self):
        record_donated_videos({1: _seen("w", EARLY), 2: _seen("l", EARLY)})

        result = record_donated_videos(
            {1: _seen("wb", EARLY), 2: _seen("l", EARLY), 3: _seen("w", EARLY)}
        )

        self.assertEqual((result.created, result.updated), (1, 2))
        self.assertEqual(_counts(), {1: (2, 0, 1), 2: (0, 2, 0), 3: (1, 0, 0)})

    def test_keeps_the_later_interactions(self):
        record_donated_videos({1: _seen("w", LATE, LATE), 2: _seen("w", EARLY)})

        record_donated_videos(
            {1: _seen("l", EARLY, EARLY), 2: _seen("l", OUTSIDE, EARLY)}
        )

        self.assertEqual(_interactions(), {1: (LATE, LATE), 2: (OUTSIDE, EARLY)})

    def test_an_interaction_without_date_does_not_erase_a_known_one(self):
        record_donated_videos({1: _seen("w", EARLY, EARLY)})

        record_donated_videos({1: _seen("l")})

        self.assertEqual(_interactions(), {1: (EARLY, EARLY)})
        self.assertEqual(_counts(), {1: (1, 1, 0)})

    def test_marks_the_video_as_changed_only_when_an_interaction_moves(self):
        record_donated_videos({1: _seen("w", EARLY), 2: _seen("w", EARLY)})
        past = datetime(2026, 1, 1, tzinfo=UTC)
        TikTokVideo.objects.update(updated_at=past)

        record_donated_videos(
            {1: _seen("wl", EARLY), 2: _seen("w", LATE), 3: _seen("w", EARLY)}
        )

        # Video 1 only had its counts raised; 2 was seen later, 3 is new.
        self.assertEqual(_counts()[1], (2, 1, 0))
        self.assertEqual(_changed_since(TikTokVideo, "id_tiktok", past), {2, 3})

    def test_marks_a_video_another_source_registered_as_changed(self):
        past = datetime(2026, 1, 1, tzinfo=UTC)
        TikTokVideo.objects.create(id_tiktok=1, added_by=DataOrigins.RESEARCH_API)
        TikTokVideo.objects.update(updated_at=past)

        record_donated_videos({1: _seen("l", EARLY)})

        self.assertGreater(TikTokVideo.objects.get().updated_at, past)

    def test_works_in_chunks(self):
        with patch("ddcs.metadata.donations.service._RECORD_CHUNK_SIZE", 2):
            result = record_donated_videos(
                dict.fromkeys(range(1, 6), _seen("w", EARLY))
            )
            reset = reset_donation_counts()

        self.assertEqual((result.created, reset), (5, 5))
        self.assertEqual(set(_counts().values()), {(0, 0, 0)})

    def test_reset_clears_counts_only(self):
        record_donated_videos({1: _seen("wlb", LATE, EARLY), 2: _seen("l", EARLY)})
        past = datetime(2026, 1, 1, tzinfo=UTC)
        TikTokVideo.objects.update(updated_at=past)
        DonationVideoInfos.objects.update(updated_at=past)

        self.assertEqual(reset_donation_counts(), 2)

        self.assertEqual(_counts(), {1: (0, 0, 0), 2: (0, 0, 0)})
        self.assertEqual(_interactions(), {1: (LATE, EARLY), 2: (EARLY, None)})
        self.assertEqual(_changed_since(TikTokVideo, "id_tiktok", past), set())
        self.assertEqual(_changed_since(DonationVideoInfos, "pk", past), set())
        # Nothing left to reset.
        self.assertEqual(reset_donation_counts(), 0)


class RegisterDonationMetadataDonationInfosTests(TestCase):
    def setUp(self):
        self.data = TikTokUserData(
            watch_history=[
                {"video_id": 1, "date": EARLY},
                {"video_id": 1, "date": OUTSIDE},
                {"video_id": 2, "date": OUTSIDE},
            ],
            liked_videos=[
                {"video_id": 2, "date": EARLY},
                {"video_id": 3, "date": LATE},
            ],
            video_bookmarks=[{"video_id": 4, "date": OUTSIDE}],
            shared_videos=[{"video_id": 5, "date": EARLY}],
        )

    @override_settings(TIKTOK_SCRAPER_ENABLED=False)
    def test_records_watched_liked_and_bookmarked_videos(self):
        register_donation_metadata(self.data)

        # Not video 5: it was only shared.
        self.assertEqual(
            _counts(), {1: (1, 0, 0), 2: (1, 1, 0), 3: (0, 1, 0), 4: (0, 0, 1)}
        )
        self.assertEqual(
            _interactions(),
            {
                1: (OUTSIDE, EARLY),
                2: (OUTSIDE, EARLY),
                3: (LATE, LATE),
                4: (OUTSIDE, None),
            },
        )

    @override_settings(TIKTOK_SCRAPER_ENABLED=True)
    def test_records_videos_the_research_api_covers(self):
        covered = TikTokVideo.objects.create(
            id_tiktok=1, added_by=DataOrigins.RESEARCH_API
        )
        APIVideoInfos.objects.create(video=covered)

        register_donation_metadata(self.data)

        self.assertIn(1, _counts())
        self.assertFalse(ScrapeTarget.objects.filter(video=covered).exists())

    def test_donation_without_videos(self):
        register_donation_metadata(
            TikTokUserData(followed_accounts=[{"username": "alice"}])
        )

        self.assertFalse(DonationVideoInfos.objects.exists())


_COMMAND = "ddcs.metadata.donations.management.commands.record_donated_videos"
_TEST_PARTICIPANT = next(iter(sorted(EXCLUDED_PARTICIPANT_IDS)))


class RecordDonatedVideosCommandTests(TestCase):
    def setUp(self):
        # Donated videos per participant; an Exception stands for a donation
        # that cannot be decrypted.
        self.donations: dict[str, TikTokUserData | Exception] = {
            "anna": TikTokUserData(
                watch_history=[_view(1, EARLY), _view(1, EARLY), _view(2, OUTSIDE)],
                liked_videos=[_view(1, LATE)],
            ),
            # No watch history at all.
            "ben": TikTokUserData(
                liked_videos=[_view(1, EARLY)],
                video_bookmarks=[_view(3, EARLY)],
            ),
        }

    def _call(self, *args: str) -> str:
        participants = [Mock(pk=name, external_id=name) for name in self.donations]

        def video_donations(participant: Mock) -> TikTokUserData:
            donation = self.donations[participant.pk]
            if isinstance(donation, Exception):
                raise donation
            return donation

        out = StringIO()
        with (
            patch(f"{_COMMAND}.participants_with_video_donations") as with_videos,
            patch(f"{_COMMAND}.get_video_donations", side_effect=video_donations),
        ):
            with_videos.return_value.iterator.return_value = iter(participants)
            call_command("record_donated_videos", *args, stdout=out)
        return out.getvalue()

    def test_counts_donors_per_kind_of_interaction(self):
        out = self._call()

        # Video 1: watched by Anna (her repeat view counts once), liked by both.
        self.assertEqual(_counts(), {1: (1, 2, 0), 2: (1, 0, 0), 3: (0, 0, 1)})
        self.assertEqual(
            _interactions(),
            {1: (LATE, LATE), 2: (OUTSIDE, None), 3: (EARLY, EARLY)},
        )
        self.assertIn("Donations read: 2", out)
        self.assertIn("Videos watched: 2", out)
        self.assertIn("Videos liked: 2", out)
        self.assertIn("Videos bookmarked: 1", out)
        self.assertIn("Videos with an interaction in the window: 3", out)
        self.assertIn("Rows created: 3", out)

    def test_queues_videos_with_an_interaction_in_the_window(self):
        out = self._call()

        # Video 1: two donors, last interaction Anna's like. Video 2 was only
        # watched outside the window.
        self.assertEqual(_ranking(), {1: (2, LATE), 3: (1, EARLY)})
        self.assertIn("Targets created: 2", out)
        self.assertIn("Counts raised on existing targets: 1", out)

    def test_rerun_counts_the_queue_from_scratch(self):
        self._call()
        # E.g. a retried donation counted twice.
        enqueue_donated_videos({1: (1, LATE)})
        self.assertEqual(_ranking()[1][0], 3)

        out = self._call()

        self.assertEqual(_ranking(), {1: (2, LATE), 3: (1, EARLY)})
        self.assertIn("Targets with ranking reset: 2", out)
        self.assertIn("Targets created: 0", out)

    def test_rerun_does_not_requeue_scraped_videos(self):
        self._call()
        ScrapeTarget.objects.filter(video__id_tiktok=1).update(
            status=ScrapeTarget.Status.SUCCESS, attempts=1
        )

        self._call()

        target = ScrapeTarget.objects.get(video__id_tiktok=1)
        self.assertEqual(
            (target.status, target.attempts), (ScrapeTarget.Status.SUCCESS, 1)
        )
        self.assertEqual(target.occurrence_count, 2)

    def test_targets_no_donation_backs_any_more_drop_to_the_end(self):
        self._call()
        del self.donations["ben"]

        self._call()

        self.assertEqual(_ranking(), {1: (1, LATE), 3: (0, None)})

    def test_videos_covered_by_the_research_api_are_reported_not_queued(self):
        covered = TikTokVideo.objects.create(
            id_tiktok=1, added_by=DataOrigins.RESEARCH_API
        )
        APIVideoInfos.objects.create(video=covered)

        out = self._call()

        # Both Anna and Ben interacted with video 1: skipped once per donation.
        self.assertIn("Skipped, Research API has the video (per donation): 2", out)
        self.assertEqual(set(_ranking()), {3})
        # It is still recorded as donated.
        self.assertEqual(_counts()[1], (1, 2, 0))

    def test_each_donation_is_stored_before_the_next_is_read(self):
        queued_before_ben = []

        def video_donations(participant: Mock) -> TikTokUserData:
            if participant.pk == "ben":
                queued_before_ben.extend(_ranking())
            return self.donations[participant.pk]

        with (
            patch(f"{_COMMAND}.participants_with_video_donations") as with_videos,
            patch(f"{_COMMAND}.get_video_donations", side_effect=video_donations),
        ):
            with_videos.return_value.iterator.return_value = iter(
                [Mock(pk="anna", external_id="anna"), Mock(pk="ben", external_id="ben")]
            )
            call_command("record_donated_videos", stdout=StringIO())

        self.assertEqual(queued_before_ben, [1])

    def test_rerun_counts_from_scratch_without_marking_videos_as_changed(self):
        self._call()
        past = datetime(2026, 1, 1, tzinfo=UTC)
        TikTokVideo.objects.update(updated_at=past)

        out = self._call()

        self.assertEqual(_counts(), {1: (1, 2, 0), 2: (1, 0, 0), 3: (0, 0, 1)})
        self.assertEqual(_changed_since(TikTokVideo, "id_tiktok", past), set())
        self.assertIn("Rows with counts reset: 3", out)
        self.assertIn("Rows created: 0", out)

    def test_rerun_corrects_counts_added_by_incoming_donations(self):
        self._call()
        # E.g. a retried donation counted twice.
        record_donated_videos({1: _seen("wl", EARLY)})
        self.assertEqual(_counts()[1], (2, 3, 0))

        self._call()

        self.assertEqual(_counts()[1], (1, 2, 0))

    def test_videos_no_donation_backs_any_more_keep_their_row(self):
        self._call()
        del self.donations["ben"]

        self._call()

        self.assertEqual(_counts(), {1: (1, 1, 0), 2: (1, 0, 0), 3: (0, 0, 0)})

    def test_test_participants_are_left_out(self):
        self.donations[_TEST_PARTICIPANT] = TikTokUserData(
            watch_history=[_view(1, EARLY), _view(99, EARLY)]
        )

        out = self._call()

        self.assertEqual(_counts(), {1: (1, 2, 0), 2: (1, 0, 0), 3: (0, 0, 1)})
        self.assertEqual(_ranking(), {1: (2, LATE), 3: (1, EARLY)})
        self.assertFalse(TikTokVideo.objects.filter(id_tiktok=99).exists())
        self.assertIn("Donations read: 2", out)
        self.assertIn("Test participants left out: 1", out)

    def test_unreadable_donation_is_skipped_and_reported(self):
        self.donations["carl"] = ValueError("cannot decrypt")

        with self.assertLogs(_COMMAND, level="ERROR"):
            out = self._call()

        self.assertIn("Donations read: 2", out)
        self.assertIn("Donations that could not be read: 1", out)
        self.assertEqual(set(_counts()), {1, 2, 3})

    def test_dry_run_changes_nothing(self):
        record_donated_videos({7: _seen("w", EARLY)})
        enqueue_donated_videos({7: (5, LATE)})

        out = self._call("--dry-run")

        self.assertEqual(_counts(), {7: (1, 0, 0)})
        self.assertEqual(_ranking(), {7: (5, LATE)})
        self.assertIn("Videos liked: 2", out)
        self.assertIn("Dry run", out)

    def test_custom_window(self):
        self._call("--start", "2026-10-01", "--end", "2026-10-31")

        self.assertEqual(
            _interactions(),
            {1: (LATE, None), 2: (OUTSIDE, OUTSIDE), 3: (EARLY, None)},
        )
        self.assertEqual(_ranking(), {2: (1, OUTSIDE)})

    def test_start_after_end_is_rejected(self):
        with self.assertRaises(CommandError):
            self._call("--start", "2026-09-01", "--end", "2026-08-01")
