import json
import os
from datetime import UTC, date, datetime, timedelta
from io import StringIO
from unittest import skipUnless
from unittest.mock import Mock, patch

from celery.exceptions import SoftTimeLimitExceeded
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from ddcs.metadata.models import (
    DataOrigins,
    TikTokHashtag,
    TikTokMusic,
    TikTokUser,
    TikTokVideo,
)
from ddcs.metadata.research_api.models import APIVideoInfos, APIVideoStatistics
from ddcs.metadata.scraper.config import PRIORITY_MIN_OCCURRENCES
from ddcs.metadata.scraper.exceptions import (
    TikTokBlockedError,
    TikTokClientGetError,
    TikTokDataExtractionError,
    TikTokItemUnavailableError,
    TikTokMissingRehydrationDataError,
)
from ddcs.metadata.scraper.models import (
    ScrapeTarget,
    VideoInfosScraped,
    VideoStatisticsScraped,
)
from ddcs.metadata.scraper.scraper import TikTokScraper
from ddcs.metadata.scraper.service import (
    ScraperService,
    cooldown_until,
    enqueue_watched_videos,
    get_cooldown,
    get_last_run,
    register_abort,
    reset_watch_ranking,
    scan_watch_history,
    watched_videos_in_window,
)
from ddcs.metadata.scraper.tasks import scrape_pending_videos

Status = ScrapeTarget.Status
CaptionStatus = VideoInfosScraped.CaptionStatus

# Shaped like the "itemStruct" of a real video page, cut down to what matters.
_PAYLOAD = {
    "id": "7470493179767344430",
    "desc": "a description #tag",
    "createTime": "1739359756",
    "video": {
        "duration": 19,
        "height": 1024,
        "width": 576,
        "playAddr": "https://v16.example/video.mp4",
        "bitrateInfo": [{"Bitrate": 1}],
    },
    "author": {
        "id": "107955",
        "uniqueId": "scraped_author",
        "avatarThumb": "https://p16.example/a.jpeg",
    },
    "music": {"id": "7470493157294115627", "title": "original sound"},
    "challenges": [{"id": "42", "title": "tag"}, {"id": "43", "title": ""}],
    "textExtra": [
        {"start": 14, "end": 18, "hashtagName": "tag", "type": 1},
    ],
    "effectStickers": [{"ID": "123", "name": "Green Screen"}],
    "stats": {"diggCount": 1, "playCount": 2},
    "statsV2": {
        "diggCount": "84600",
        "shareCount": "514",
        "commentCount": "2027",
        "playCount": "514600",
        "collectCount": "58690",
        "repostCount": "7",
    },
    "locationCreated": "US",
    "textLanguage": "en",
    "CategoryType": 120,
    "originalItem": False,
    "officalItem": False,
    "privateItem": False,
    "isAd": True,
    "IsAigc": False,
    "AIGCDescription": "",
    "diversificationLabels": ["a", "b"],
    "diversificationId": 10075,
}


def _success(data: dict | None = None) -> dict:
    return {"success": True, "data": data or _PAYLOAD, "video_id": "x"}


def _error(exception: Exception) -> dict:
    return {
        "success": False,
        "error": str(exception),
        "error_type": type(exception).__name__,
        "exception": exception,
        "video_id": "x",
    }


def _video(id_tiktok: int, **kwargs) -> TikTokVideo:
    kwargs.setdefault("added_by", DataOrigins.DONATION)
    return TikTokVideo.objects.create(id_tiktok=id_tiktok, **kwargs)


def _target(video: TikTokVideo, **kwargs) -> ScrapeTarget:
    return ScrapeTarget.objects.create(video=video, **kwargs)


_MIN = PRIORITY_MIN_OCCURRENCES

# A moment inside the watch window (2026-07-01 .. 2026-09-20).
_WATCHED_AT = datetime(2026, 8, 1, 12, tzinfo=UTC)


def enqueue_videos(id_tiktoks: list[int]) -> int:
    """Queue videos as watched once by one donor; returns targets created."""
    return enqueue_watched_videos(dict.fromkeys(id_tiktoks, (1, _WATCHED_AT))).created


def _ranking(id_tiktok: int) -> tuple[int, datetime | None]:
    target = ScrapeTarget.objects.get(video__id_tiktok=id_tiktok)
    return target.occurrence_count, target.last_watched_at


_VTT = "WEBVTT\n\n00:00:00.400 --> 00:00:01.600\nHallo zusammen\n"
_CAPTION = {"language": "deu-DE", "is_auto_generated": False, "vtt": _VTT}


def _service(
    *results: dict,
    caption: dict | Exception | None = None,
    fetch_captions: bool = True,
) -> tuple[ScraperService, Mock]:
    scraper = Mock()
    scraper.scrape_video_list.side_effect = lambda ids: iter(results[: len(ids)])
    if isinstance(caption, Exception):
        scraper.fetch_original_caption.side_effect = caption
    else:
        scraper.fetch_original_caption.return_value = caption
    service = ScraperService(
        scraper=scraper, max_attempts=3, fetch_captions=fetch_captions
    )
    return service, scraper


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
        self.assertEqual(watched_videos_in_window(None), {})


class EnqueueWatchedVideosTests(TestCase):
    def setUp(self):
        self.early = datetime(2026, 7, 5, 10, tzinfo=UTC)
        self.late = datetime(2026, 8, 5, 10, tzinfo=UTC)

    def test_creates_targets_and_missing_videos(self):
        _video(1)

        result = enqueue_watched_videos({1: (3, self.late), 999: (1, self.early)})

        self.assertEqual(
            (result.created, result.updated, result.covered_by_api), (2, 0, 0)
        )
        self.assertEqual(_ranking(1), (3, self.late))
        self.assertEqual(_ranking(999), (1, self.early))
        created_video = TikTokVideo.objects.get(id_tiktok=999)
        self.assertEqual(created_video.added_by, DataOrigins.DONATION)
        self.assertEqual(
            ScrapeTarget.objects.get(video=created_video).status, Status.PENDING
        )

    def test_skips_videos_the_research_api_covers(self):
        APIVideoInfos.objects.create(video=_video(1))
        _video(2)

        result = enqueue_watched_videos({1: (5, self.late), 2: (1, self.late)})

        self.assertEqual((result.created, result.covered_by_api), (1, 1))
        self.assertEqual(ScrapeTarget.objects.get().video.id_tiktok, 2)

    def test_adding_sums_counts_and_keeps_the_later_view(self):
        enqueue_watched_videos({1: (2, self.late), 2: (1, self.early)})

        result = enqueue_watched_videos({1: (1, self.early), 2: (1, self.late)})

        self.assertEqual((result.created, result.updated), (0, 2))
        self.assertEqual(_ranking(1), (3, self.late))
        self.assertEqual(_ranking(2), (2, self.late))

    def test_adding_leaves_other_targets_alone(self):
        enqueue_watched_videos({1: (5, self.late)})

        enqueue_watched_videos({2: (1, self.early)})

        self.assertEqual(_ranking(1), (5, self.late))

    def test_finished_targets_keep_their_status(self):
        _target(_video(1), status=Status.SUCCESS, attempts=1)
        _target(_video(2), status=Status.UNAVAILABLE, attempts=1)

        enqueue_watched_videos({1: (2, self.late), 2: (2, self.late)})

        self.assertEqual(
            set(ScrapeTarget.objects.values_list("status", "attempts")),
            {(Status.SUCCESS, 1), (Status.UNAVAILABLE, 1)},
        )
        self.assertEqual(_ranking(1), (2, self.late))

    def test_reset_watch_ranking_clears_counts_and_dates_only(self):
        enqueue_watched_videos({1: (5, self.late), 2: (1, self.early)})
        _target(_video(3), status=Status.SUCCESS, attempts=2, occurrence_count=4)
        _target(_video(4))  # nothing to reset

        with patch("ddcs.metadata.scraper.service._RESET_CHUNK_SIZE", 2):
            reset = reset_watch_ranking()

        self.assertEqual(reset, 3)
        self.assertEqual(
            set(
                ScrapeTarget.objects.values_list("occurrence_count", "last_watched_at")
            ),
            {(0, None)},
        )
        finished = ScrapeTarget.objects.get(video__id_tiktok=3)
        self.assertEqual((finished.status, finished.attempts), (Status.SUCCESS, 2))
        self.assertEqual(ScrapeTarget.objects.count(), 4)


class ScraperServiceStoreTests(TestCase):
    def test_success_stores_infos_statistics_and_marks_target(self):
        video = _video(7470493179767344430)
        enqueue_videos([video.id_tiktok])
        service, scraper = _service(_success())

        stats = service.scrape_batch(limit=10)

        scraper.scrape_video_list.assert_called_once_with(["7470493179767344430"])
        self.assertEqual(stats["scraped"], 1)

        infos = VideoInfosScraped.objects.get(video=video)
        self.assertEqual(infos.description, "a description #tag")
        self.assertEqual(infos.create_time, datetime.fromtimestamp(1739359756, tz=UTC))
        self.assertEqual(infos.location_created, "US")
        self.assertEqual(infos.text_language, "en")
        self.assertEqual(infos.category_type, 120)
        self.assertEqual((infos.duration, infos.height, infos.width), (19, 1024, 576))
        self.assertIs(infos.is_ad, True)
        self.assertIs(infos.is_aigc, False)
        self.assertEqual(infos.diversification_labels, ["a", "b"])
        self.assertEqual(infos.diversification_id, 10075)

        statistics = VideoStatisticsScraped.objects.get(video=video)
        self.assertEqual(statistics.view_count, 514600)
        self.assertEqual(statistics.like_count, 84600)
        self.assertEqual(statistics.comment_count, 2027)
        self.assertEqual(statistics.share_count, 514)
        self.assertEqual(statistics.favorites_count, 58690)
        self.assertEqual(statistics.repost_count, 7)

        target = ScrapeTarget.objects.get()
        self.assertEqual((target.status, target.attempts), (Status.SUCCESS, 1))
        self.assertIsNotNone(target.last_attempted_at)

    def test_raw_keeps_data_but_drops_urls_and_encoding_details(self):
        enqueue_videos([_video(1).id_tiktok])
        service, _ = _service(_success())

        service.scrape_batch(limit=10)

        raw = VideoInfosScraped.objects.get().raw
        self.assertEqual(raw["video"], {"duration": 19, "height": 1024, "width": 576})
        self.assertEqual(raw["author"], {"id": "107955", "uniqueId": "scraped_author"})
        self.assertEqual(raw["statsV2"]["repostCount"], "7")

    def test_success_fills_in_missing_base_model_links(self):
        video = _video(7470493179767344430)
        enqueue_videos([video.id_tiktok])
        service, _ = _service(_success())

        service.scrape_batch(limit=10)

        video.refresh_from_db()
        self.assertIsNotNone(video.scraped_at)
        self.assertIsNotNone(video.inferred_create_time)
        self.assertEqual(video.user.name, "scraped_author")
        self.assertEqual(video.user.id_tiktok, 107955)
        self.assertEqual(video.user.added_by, DataOrigins.SCRAPER)
        self.assertEqual(video.music.id_tiktok, 7470493157294115627)
        self.assertEqual(video.music.added_by, DataOrigins.SCRAPER)
        hashtag = video.hashtags.get()
        self.assertEqual((hashtag.name, hashtag.id_tiktok), ("tag", 42))
        self.assertEqual(hashtag.added_by, DataOrigins.SCRAPER)

    def test_success_does_not_overwrite_existing_links(self):
        user = TikTokUser.objects.create(name="known", added_by=DataOrigins.IMPORT)
        music = TikTokMusic.objects.create(id_tiktok=5, added_by=DataOrigins.IMPORT)
        other_tag = TikTokHashtag.objects.create(
            name="other", added_by=DataOrigins.RESEARCH_API
        )
        inferred = timezone.now() - timedelta(days=3)
        video = _video(1, user=user, music=music, inferred_create_time=inferred)
        video.hashtags.add(other_tag)
        enqueue_videos([1])
        service, _ = _service(_success())

        service.scrape_batch(limit=10)

        video.refresh_from_db()
        self.assertEqual(video.user, user)
        self.assertEqual(video.music, music)
        self.assertEqual(video.inferred_create_time, inferred)
        self.assertEqual(
            set(video.hashtags.values_list("name", flat=True)), {"other", "tag"}
        )
        self.assertFalse(TikTokUser.objects.filter(name="scraped_author").exists())

    def test_reuses_existing_user_and_hashtag_without_changing_origin(self):
        TikTokUser.objects.create(
            name="scraped_author", added_by=DataOrigins.RESEARCH_API
        )
        TikTokHashtag.objects.create(name="tag", added_by=DataOrigins.RESEARCH_API)
        enqueue_videos([_video(1).id_tiktok])
        service, _ = _service(_success())

        service.scrape_batch(limit=10)

        self.assertEqual(
            TikTokUser.objects.get(name="scraped_author").added_by,
            DataOrigins.RESEARCH_API,
        )
        self.assertEqual(
            TikTokHashtag.objects.get(name="tag").added_by, DataOrigins.RESEARCH_API
        )

    def test_sparse_payload_is_stored_without_error(self):
        enqueue_videos([_video(1).id_tiktok])
        service, _ = _service(_success({"id": "1"}))

        stats = service.scrape_batch(limit=10)

        self.assertEqual(stats["scraped"], 1)
        infos = VideoInfosScraped.objects.get()
        self.assertEqual(infos.description, "")
        self.assertIsNone(infos.create_time)
        self.assertEqual(infos.video_mention_list, [])
        self.assertIsNone(infos.effect_list)
        self.assertIsNone(VideoStatisticsScraped.objects.get().view_count)

    def test_mentions_match_the_research_api_format(self):
        # Offsets are UTF-16 code units: the emoji counts as two.
        description = "Fokus 🥊 #boxen @arian_ejupi_ @PrimeTime Promotion "
        payload = {
            **_PAYLOAD,
            "desc": description,
            "textExtra": [
                {"start": 9, "end": 15, "hashtagName": "boxen", "type": 1},
                {"start": 16, "end": 29, "type": 0, "userUniqueId": "arian_ejupi_"},
                {
                    "start": 30,
                    "end": 50,
                    "type": 0,
                    "userUniqueId": "primetimepromotion",
                },
            ],
        }
        enqueue_videos([_video(1).id_tiktok])
        service, _ = _service(_success(payload))

        service.scrape_batch(limit=10)

        self.assertEqual(
            VideoInfosScraped.objects.get().video_mention_list,
            ["arian_ejupi_", "PrimeTime Promotion"],
        )

    def test_effect_list_is_stored_as_scraped(self):
        enqueue_videos([_video(1).id_tiktok])
        service, _ = _service(_success())

        service.scrape_batch(limit=10)

        infos = VideoInfosScraped.objects.get()
        self.assertEqual(infos.effect_list, [{"ID": "123", "name": "Green Screen"}])
        self.assertEqual(infos.video_mention_list, [])

    def test_shared_fields_exist_on_the_research_api_models(self):
        api_infos = {f.name: type(f) for f in APIVideoInfos._meta.get_fields()}
        for name in (
            "description",
            "create_time",
            "duration",
            "video_mention_list",
            "effect_list",
            "voice_to_text",
        ):
            with self.subTest(field=name):
                self.assertIs(
                    type(VideoInfosScraped._meta.get_field(name)), api_infos[name]
                )

        api_statistics = {
            f.name: type(f) for f in APIVideoStatistics._meta.get_fields()
        }
        for name in (
            "view_count",
            "like_count",
            "comment_count",
            "share_count",
            "favorites_count",
        ):
            with self.subTest(field=name):
                self.assertIs(
                    type(VideoStatisticsScraped._meta.get_field(name)),
                    api_statistics[name],
                )

    def test_unstorable_payload_marks_failed_and_keeps_batch_going(self):
        enqueue_videos([_video(1).id_tiktok, _video(2).id_tiktok])
        service, _ = _service(_success(), _success())

        with patch.object(
            ScraperService,
            "_clean_video",
            side_effect=[
                ValueError("odd payload"),
                ScraperService._clean_video(_PAYLOAD),
            ],
        ):
            stats = service.scrape_batch(limit=10)

        self.assertEqual((stats["failed"], stats["scraped"]), (1, 1))
        failed = ScrapeTarget.objects.get(status=Status.FAILED)
        self.assertEqual(failed.last_error_type, "ValueError")
        # Nothing half-written for the failed video.
        self.assertFalse(VideoInfosScraped.objects.filter(video=failed.video).exists())
        self.assertEqual(ScrapeTarget.objects.filter(status=Status.SUCCESS).count(), 1)

    def test_soft_time_limit_is_not_swallowed(self):
        enqueue_videos([_video(1).id_tiktok])
        service, _ = _service(_success())

        with (
            patch.object(ScraperService, "_store", side_effect=SoftTimeLimitExceeded()),
            self.assertRaises(SoftTimeLimitExceeded),
        ):
            service.scrape_batch(limit=10)


class ScraperServiceCaptionTests(TestCase):
    def setUp(self):
        self.video = _video(1)
        enqueue_videos([1])

    def test_caption_is_stored_as_text_and_as_downloaded(self):
        service, scraper = _service(_success(), caption=_CAPTION)

        stats = service.scrape_batch(limit=10)

        scraper.fetch_original_caption.assert_called_once_with(_PAYLOAD)
        infos = VideoInfosScraped.objects.get()
        self.assertEqual(infos.caption_status, CaptionStatus.FETCHED)
        self.assertEqual(infos.voice_to_text, "Hallo zusammen")
        self.assertEqual(infos.caption_vtt, _VTT)
        self.assertEqual(infos.caption_language, "deu-DE")
        self.assertIs(infos.caption_is_auto_generated, False)
        self.assertEqual((stats["captions_fetched"], stats["captions_failed"]), (1, 0))

    def test_video_without_caption(self):
        service, _ = _service(_success(), caption=None)

        stats = service.scrape_batch(limit=10)

        infos = VideoInfosScraped.objects.get()
        self.assertEqual(infos.caption_status, CaptionStatus.NONE_AVAILABLE)
        self.assertEqual((infos.voice_to_text, infos.caption_vtt), ("", ""))
        self.assertEqual((stats["captions_fetched"], stats["captions_failed"]), (0, 0))

    def test_failed_caption_download_does_not_fail_the_video(self):
        for error in (TikTokBlockedError("blocked"), TikTokClientGetError("gone")):
            with self.subTest(error=error):
                VideoInfosScraped.objects.all().delete()
                ScrapeTarget.objects.update(status=Status.PENDING)
                service, _ = _service(_success(), caption=error)

                stats = service.scrape_batch(limit=10)

                self.assertEqual((stats["scraped"], stats["captions_failed"]), (1, 1))
                self.assertFalse(stats["aborted"])
                self.assertEqual(stats["blocked"], 0)
                infos = VideoInfosScraped.objects.get()
                self.assertEqual(infos.caption_status, CaptionStatus.FAILED)
                self.assertEqual(infos.voice_to_text, "")
                self.assertEqual(ScrapeTarget.objects.get().status, Status.SUCCESS)

    def test_captions_switched_off(self):
        service, scraper = _service(_success(), caption=_CAPTION, fetch_captions=False)

        service.scrape_batch(limit=10)

        scraper.fetch_original_caption.assert_not_called()
        infos = VideoInfosScraped.objects.get()
        self.assertEqual(infos.caption_status, CaptionStatus.NOT_REQUESTED)
        self.assertEqual(infos.voice_to_text, "")

    @override_settings(TIKTOK_SCRAPER_FETCH_CAPTIONS=False)
    def test_setting_is_the_default_for_fetching_captions(self):
        self.assertFalse(ScraperService(scraper=Mock()).fetch_captions)

    def test_no_caption_request_for_videos_that_were_not_scraped(self):
        service, scraper = _service(
            _error(TikTokItemUnavailableError(10204, "gone")), caption=_CAPTION
        )

        service.scrape_batch(limit=10)

        scraper.fetch_original_caption.assert_not_called()


class ScraperServiceQueueTests(TestCase):
    def test_unavailable_is_terminal_and_keeps_status_code(self):
        enqueue_videos([_video(1).id_tiktok])
        service, scraper = _service(
            _error(TikTokItemUnavailableError(10204, "item doesn't exist"))
        )

        stats = service.scrape_batch(limit=10)

        target = ScrapeTarget.objects.get()
        self.assertEqual(stats["unavailable"], 1)
        self.assertEqual(target.status, Status.UNAVAILABLE)
        self.assertEqual(target.tiktok_status_code, 10204)
        self.assertEqual(target.last_error_type, "TikTokItemUnavailableError")

        scraper.scrape_video_list.reset_mock()
        service.scrape_batch(limit=10)
        scraper.scrape_video_list.assert_called_once_with([])

    def test_other_errors_mark_failed_and_wait_for_backoff(self):
        enqueue_videos([_video(1).id_tiktok])
        service, scraper = _service(_error(TikTokDataExtractionError("no key")))

        stats = service.scrape_batch(limit=10)

        target = ScrapeTarget.objects.get()
        self.assertEqual(stats["failed"], 1)
        self.assertEqual((target.status, target.attempts), (Status.FAILED, 1))
        self.assertEqual(target.last_error_msg, "no key")

        # Too soon: not picked up again.
        scraper.scrape_video_list.reset_mock()
        service.scrape_batch(limit=10)
        scraper.scrape_video_list.assert_called_once_with([])

    def test_failed_target_is_retried_after_backoff_until_max_attempts(self):
        video = _video(1)
        long_ago = timezone.now() - ScraperService.FAILED_RETRY_BACKOFF * 2
        target = _target(
            video, status=Status.FAILED, attempts=2, last_attempted_at=long_ago
        )
        service, scraper = _service(_error(TikTokDataExtractionError("no key")))

        service.scrape_batch(limit=10)

        scraper.scrape_video_list.assert_called_once_with(["1"])
        target.refresh_from_db()
        self.assertEqual(target.attempts, 3)

        # Max attempts reached: stays failed for good.
        ScrapeTarget.objects.update(last_attempted_at=long_ago)
        scraper.scrape_video_list.reset_mock()
        service.scrape_batch(limit=10)
        scraper.scrape_video_list.assert_called_once_with([])

    def test_blocked_leaves_target_pending_and_untouched(self):
        enqueue_videos([_video(1).id_tiktok])
        service, _ = _service(_error(TikTokBlockedError("blocked")))

        stats = service.scrape_batch(limit=10)

        target = ScrapeTarget.objects.get()
        self.assertEqual((stats["blocked"], stats["aborted"]), (1, False))
        self.assertEqual((target.status, target.attempts), (Status.PENDING, 0))

    def test_three_consecutive_blocks_abort_the_batch(self):
        enqueue_videos([_video(i).id_tiktok for i in range(1, 6)])
        blocked = _error(TikTokBlockedError("blocked"))
        service, _ = _service(blocked, blocked, blocked, _success(), _success())

        stats = service.scrape_batch(limit=10)

        self.assertTrue(stats["aborted"])
        self.assertEqual((stats["blocked"], stats["scraped"]), (3, 0))
        self.assertEqual(ScrapeTarget.objects.filter(status=Status.PENDING).count(), 5)

    def test_block_abort_reports_its_reason(self):
        enqueue_videos([_video(i).id_tiktok for i in range(1, 4)])
        blocked = _error(TikTokBlockedError("blocked"))
        service, _ = _service(blocked, blocked, blocked)

        stats = service.scrape_batch(limit=10)

        self.assertEqual(stats["abort_reason"], "blocked")

    def test_five_consecutive_failures_abort_and_leave_targets_untouched(self):
        enqueue_videos([_video(i).id_tiktok for i in range(1, 8)])
        failure = _error(TikTokMissingRehydrationDataError("no data"))
        service, _ = _service(*[failure] * 5, _success(), _success())

        stats = service.scrape_batch(limit=10)

        self.assertTrue(stats["aborted"])
        self.assertEqual(stats["abort_reason"], "consecutive_failures")
        self.assertEqual((stats["failed"], stats["scraped"]), (0, 0))
        # Nothing was burnt: every target is still pending with no attempt.
        self.assertEqual(
            set(ScrapeTarget.objects.values_list("status", "attempts")),
            {(Status.PENDING, 0)},
        )
        self.assertEqual(ScrapeTarget.objects.count(), 7)

    def test_network_errors_count_as_failures_for_the_abort(self):
        enqueue_videos([_video(i).id_tiktok for i in range(1, 6)])
        service, _ = _service(*[_error(TikTokClientGetError("timeout"))] * 5)

        stats = service.scrape_batch(limit=10)

        self.assertEqual(stats["abort_reason"], "consecutive_failures")

    def test_failures_before_a_success_are_recorded_as_failed(self):
        enqueue_videos([_video(i).id_tiktok for i in range(1, 6)])
        failure = _error(TikTokDataExtractionError("no key"))
        service, _ = _service(*[failure] * 4, _success())

        stats = service.scrape_batch(limit=10)

        self.assertFalse(stats["aborted"])
        self.assertEqual((stats["failed"], stats["scraped"]), (4, 1))
        failed = ScrapeTarget.objects.filter(status=Status.FAILED)
        self.assertEqual(failed.count(), 4)
        self.assertEqual(set(failed.values_list("attempts", flat=True)), {1})

    def test_an_unavailable_video_resets_the_failure_streak(self):
        enqueue_videos([_video(i).id_tiktok for i in range(1, 10)])
        failure = _error(TikTokDataExtractionError("no key"))
        unavailable = _error(TikTokItemUnavailableError(10204, "gone"))
        service, _ = _service(*[failure] * 4, unavailable, *[failure] * 4)

        stats = service.scrape_batch(limit=10)

        self.assertFalse(stats["aborted"])
        self.assertEqual((stats["failed"], stats["unavailable"]), (8, 1))

    def test_short_failure_streak_at_the_end_is_recorded_as_failed(self):
        enqueue_videos([_video(i).id_tiktok for i in range(1, 4)])
        failure = _error(TikTokDataExtractionError("no key"))
        service, _ = _service(_success(), failure, failure)

        stats = service.scrape_batch(limit=10)

        self.assertFalse(stats["aborted"])
        self.assertEqual(stats["failed"], 2)
        self.assertEqual(ScrapeTarget.objects.filter(status=Status.FAILED).count(), 2)

    def test_blocks_and_failures_are_counted_separately(self):
        enqueue_videos([_video(i).id_tiktok for i in range(1, 8)])
        blocked = _error(TikTokBlockedError("blocked"))
        failure = _error(TikTokDataExtractionError("no key"))
        # Two blocks and four failures interleaved: neither limit is reached.
        service, _ = _service(failure, blocked, failure, failure, blocked, failure)

        stats = service.scrape_batch(limit=6)

        self.assertFalse(stats["aborted"])
        self.assertEqual((stats["blocked"], stats["failed"]), (2, 4))

    def test_a_failure_does_not_reset_the_block_counter(self):
        enqueue_videos([_video(i).id_tiktok for i in range(1, 6)])
        blocked = _error(TikTokBlockedError("blocked"))
        failure = _error(TikTokDataExtractionError("no key"))
        service, _ = _service(blocked, blocked, failure, blocked, _success())

        stats = service.scrape_batch(limit=10)

        self.assertEqual(stats["abort_reason"], "blocked")
        # The single failure before the abort is an ordinary one.
        self.assertEqual(stats["failed"], 1)

    def test_a_success_resets_the_block_counter(self):
        enqueue_videos([_video(i).id_tiktok for i in range(1, 6)])
        blocked = _error(TikTokBlockedError("blocked"))
        service, _ = _service(blocked, blocked, _success(), blocked, blocked)

        stats = service.scrape_batch(limit=10)

        self.assertFalse(stats["aborted"])
        self.assertEqual((stats["blocked"], stats["scraped"]), (4, 1))

    def test_targets_covered_by_api_in_the_meantime_are_skipped(self):
        covered, missing = _video(1), _video(2)
        enqueue_videos([1, 2])
        APIVideoInfos.objects.create(video=covered)
        service, scraper = _service(_success())

        stats = service.scrape_batch(limit=10)

        scraper.scrape_video_list.assert_called_once_with(["2"])
        self.assertEqual(stats["covered_by_api"], 1)
        self.assertEqual(
            ScrapeTarget.objects.get(video=covered).status, Status.COVERED_BY_API
        )
        self.assertEqual(ScrapeTarget.objects.get(video=missing).status, Status.SUCCESS)

    def test_queue_order_is_priority_group_by_count_then_most_recent_view(self):
        before_cutoff = datetime(2026, 7, 31, 23, 59, tzinfo=UTC)
        cutoff = datetime(2026, 8, 1, tzinfo=UTC)
        late = datetime(2026, 9, 5, tzinfo=UTC)
        _target(_video(1), occurrence_count=0, last_watched_at=None)
        # Many donors, but last watched before the cutoff: not prioritised.
        _target(_video(2), occurrence_count=_MIN + 40, last_watched_at=before_cutoff)
        # Below the count threshold: ordered by view only, whatever the count.
        _target(_video(3), occurrence_count=_MIN - 1, last_watched_at=cutoff)
        _target(_video(4), occurrence_count=1, last_watched_at=late)
        # Priority group: most donors first, then most recent view.
        _target(_video(5), occurrence_count=_MIN, last_watched_at=cutoff)
        _target(_video(6), occurrence_count=_MIN, last_watched_at=late)
        _target(_video(7), occurrence_count=_MIN + 20, last_watched_at=cutoff)
        service, scraper = _service(*[_success()] * 7)

        service.scrape_batch(limit=10)

        scraper.scrape_video_list.assert_called_once_with(
            ["7", "6", "5", "4", "3", "2", "1"]
        )

    def test_priority_group_fills_the_batch_before_recent_views(self):
        late = datetime(2026, 9, 5, tzinfo=UTC)
        _target(_video(1), occurrence_count=1, last_watched_at=late)
        _target(_video(2), occurrence_count=_MIN, last_watched_at=_WATCHED_AT)
        _target(_video(3), occurrence_count=_MIN + 10, last_watched_at=_WATCHED_AT)
        service, scraper = _service(_success(), _success())

        service.scrape_batch(limit=2)

        scraper.scrape_video_list.assert_called_once_with(["3", "2"])

    def test_limit_takes_the_top_of_the_queue(self):
        _target(_video(1), occurrence_count=_MIN, last_watched_at=_WATCHED_AT)
        _target(_video(2), occurrence_count=_MIN + 10, last_watched_at=_WATCHED_AT)
        service, scraper = _service(_success())

        service.scrape_batch(limit=1)

        scraper.scrape_video_list.assert_called_once_with(["2"])

    def test_stops_starting_videos_after_the_deadline(self):
        enqueue_videos([_video(1).id_tiktok, _video(2).id_tiktok])
        service, _ = _service(_success(), _success())

        # Clock readings: batch start, check before video 1, check before
        # video 2 (past the deadline), batch end.
        with patch(
            "ddcs.metadata.scraper.service.time.monotonic",
            side_effect=[0.0, 10.0, 100.0, 100.0],
        ):
            stats = service.scrape_batch(limit=10, deadline=50.0)

        self.assertEqual(stats["scraped"], 1)
        self.assertEqual(ScrapeTarget.objects.filter(status=Status.PENDING).count(), 1)

    def test_reports_duration_and_throughput(self):
        enqueue_videos([_video(i).id_tiktok for i in range(1, 4)])
        service, _ = _service(
            _success(),
            _error(TikTokItemUnavailableError(10204, "gone")),
            _error(TikTokBlockedError("blocked")),
        )

        # Clock readings: batch start, batch end (no deadline checks).
        with patch(
            "ddcs.metadata.scraper.service.time.monotonic", side_effect=[0.0, 90.0]
        ):
            stats = service.scrape_batch(limit=10)

        # All three cost a request, whatever came of it: 3 in 90 s.
        self.assertEqual(stats["seconds"], 90.0)
        self.assertEqual(stats["videos_per_minute"], 2.0)

    def test_empty_queue_reports_zero_throughput(self):
        service, _ = _service()

        stats = service.scrape_batch(limit=10)

        self.assertEqual(stats["videos_per_minute"], 0.0)


_STATS = {
    "scraped": 1,
    "unavailable": 0,
    "aborted": False,
    "abort_reason": "",
    "videos_per_minute": 30.0,
}
_ABORTED_STATS = {**_STATS, "scraped": 0, "aborted": True, "abort_reason": "blocked"}
_APPLY_ASYNC = "ddcs.metadata.scraper.tasks.scrape_pending_videos.apply_async"
_TASK_LOGGER = "ddcs.metadata.scraper.tasks"


class ScrapePendingVideosTaskTests(TestCase):
    def setUp(self):
        redis_patcher = patch("ddcs.metadata.scraper.tasks.Redis")
        self.lock = redis_patcher.start().from_url.return_value.lock.return_value
        self.lock.acquire.return_value = True
        self.addCleanup(redis_patcher.stop)

        service_patcher = patch("ddcs.metadata.scraper.tasks.ScraperService")
        self.service_cls = service_patcher.start()
        self.service_cls.CONSECUTIVE_BLOCKS_BEFORE_ABORT = 3
        self.scrape_batch = self.service_cls.return_value.scrape_batch
        self.scrape_batch.return_value = _STATS
        self.addCleanup(service_patcher.stop)

        cache.clear()
        self.addCleanup(cache.clear)

    @override_settings(TIKTOK_SCRAPER_ENABLED=False)
    def test_does_nothing_when_disabled(self):
        self.assertIsNone(scrape_pending_videos())

        self.lock.acquire.assert_not_called()
        self.service_cls.assert_not_called()

    @override_settings(TIKTOK_SCRAPER_ENABLED=True)
    def test_skips_run_when_lock_is_held(self):
        self.lock.acquire.return_value = False

        self.assertIsNone(scrape_pending_videos())

        self.service_cls.assert_not_called()
        self.lock.release.assert_not_called()

    @override_settings(TIKTOK_SCRAPER_ENABLED=True, TIKTOK_SCRAPER_BATCH_SIZE=77)
    def test_scrapes_one_batch_and_releases_lock(self):
        self.assertEqual(scrape_pending_videos(), _STATS)

        self.assertEqual(self.scrape_batch.call_args.kwargs["limit"], 77)
        self.assertIsNotNone(self.scrape_batch.call_args.kwargs["deadline"])
        self.lock.release.assert_called_once_with()

    @override_settings(TIKTOK_SCRAPER_ENABLED=True)
    def test_max_videos_overrides_batch_size(self):
        scrape_pending_videos(max_videos=5)

        self.assertEqual(self.scrape_batch.call_args.kwargs["limit"], 5)

    @override_settings(TIKTOK_SCRAPER_ENABLED=True)
    def test_aborted_run_logs_an_error(self):
        self.scrape_batch.return_value = _ABORTED_STATS

        with self.assertLogs("ddcs.metadata.scraper.tasks", level="ERROR"):
            scrape_pending_videos()

    @override_settings(TIKTOK_SCRAPER_ENABLED=True)
    def test_finished_run_is_remembered_in_json_safe_form(self):
        scrape_pending_videos()

        last_run = get_last_run()
        self.assertEqual(last_run["videos_per_minute"], 30.0)
        self.assertEqual(last_run["scraped"], 1)
        # Must survive a JSON round trip (some cache tooling serialises to JSON).
        self.assertEqual(json.loads(json.dumps(last_run)), last_run)
        datetime.fromisoformat(last_run["finished_at"])

    @override_settings(TIKTOK_SCRAPER_ENABLED=True, CELERY_TASK_ALWAYS_EAGER=False)
    def test_queues_next_run_while_targets_are_pending(self):
        _target(_video(1))

        with patch(_APPLY_ASYNC) as apply_async:
            scrape_pending_videos()

        apply_async.assert_called_once_with(countdown=5)
        # The next run must be able to take the lock.
        self.lock.release.assert_called_once_with()

    @override_settings(TIKTOK_SCRAPER_ENABLED=True, CELERY_TASK_ALWAYS_EAGER=False)
    def test_does_not_queue_next_run_when_nothing_is_pending(self):
        _target(_video(1), status=Status.SUCCESS)
        _target(_video(2), status=Status.FAILED)

        with patch(_APPLY_ASYNC) as apply_async:
            scrape_pending_videos()

        apply_async.assert_not_called()

    @override_settings(TIKTOK_SCRAPER_ENABLED=True, CELERY_TASK_ALWAYS_EAGER=False)
    def test_does_not_queue_next_run_after_an_abort(self):
        _target(_video(1))
        self.scrape_batch.return_value = _ABORTED_STATS

        with (
            patch(_APPLY_ASYNC) as apply_async,
            self.assertLogs("ddcs.metadata.scraper.tasks", level="ERROR"),
        ):
            scrape_pending_videos()

        apply_async.assert_not_called()

    @override_settings(TIKTOK_SCRAPER_ENABLED=True, CELERY_TASK_ALWAYS_EAGER=False)
    def test_manual_run_with_max_videos_is_a_one_off(self):
        _target(_video(1))

        with patch(_APPLY_ASYNC) as apply_async:
            scrape_pending_videos(max_videos=5)

        apply_async.assert_not_called()

    @override_settings(TIKTOK_SCRAPER_ENABLED=True, CELERY_TASK_ALWAYS_EAGER=True)
    def test_does_not_queue_next_run_in_eager_mode(self):
        _target(_video(1))

        with patch(_APPLY_ASYNC) as apply_async:
            scrape_pending_videos()

        apply_async.assert_not_called()

    @override_settings(TIKTOK_SCRAPER_ENABLED=True, CELERY_TASK_ALWAYS_EAGER=False)
    def test_skipped_run_queues_nothing(self):
        _target(_video(1))
        self.lock.acquire.return_value = False

        with patch(_APPLY_ASYNC) as apply_async:
            scrape_pending_videos()

        apply_async.assert_not_called()
        self.assertIsNone(get_last_run())

    @override_settings(TIKTOK_SCRAPER_ENABLED=True)
    def test_aborts_pause_scraping_for_doubling_periods_up_to_a_day(self):
        self.scrape_batch.return_value = _ABORTED_STATS
        expected_hours = [1, 2, 4, 8, 16, 24, 24]

        for aborts, hours in enumerate(expected_hours, start=1):
            with self.subTest(aborts=aborts), self.assertLogs(_TASK_LOGGER, "ERROR"):
                before = timezone.now()
                # max_videos: a manual run, so the cool-down doesn't skip it.
                scrape_pending_videos(max_videos=1)

                cooldown = get_cooldown()
                self.assertEqual(cooldown["consecutive_aborts"], aborts)
                pause = datetime.fromisoformat(cooldown["until"]) - before
                self.assertAlmostEqual(pause.total_seconds(), hours * 3600, delta=5)
                self.assertEqual(json.loads(json.dumps(cooldown)), cooldown)

    @override_settings(TIKTOK_SCRAPER_ENABLED=True, CELERY_TASK_ALWAYS_EAGER=False)
    def test_run_is_skipped_during_a_cooldown(self):
        _target(_video(1))
        register_abort()

        with patch(_APPLY_ASYNC) as apply_async:
            self.assertIsNone(scrape_pending_videos())

        self.service_cls.assert_not_called()
        self.lock.acquire.assert_not_called()
        apply_async.assert_not_called()

    @override_settings(TIKTOK_SCRAPER_ENABLED=True)
    def test_run_proceeds_once_the_cooldown_has_passed(self):
        register_abort()
        later = timezone.now() + timedelta(hours=1, minutes=1)

        with patch("ddcs.metadata.scraper.service.timezone.now", return_value=later):
            self.assertIsNone(cooldown_until())
            self.assertEqual(scrape_pending_videos(), _STATS)

    @override_settings(TIKTOK_SCRAPER_ENABLED=True)
    def test_manual_run_ignores_the_cooldown(self):
        register_abort()

        self.assertEqual(scrape_pending_videos(max_videos=5), _STATS)

    @override_settings(TIKTOK_SCRAPER_ENABLED=True)
    def test_healthy_run_ends_the_cooldown_and_forgets_previous_aborts(self):
        register_abort()
        register_abort()

        scrape_pending_videos(max_videos=5)

        self.assertIsNone(get_cooldown())

    @override_settings(TIKTOK_SCRAPER_ENABLED=True)
    def test_unavailable_videos_also_count_as_healthy(self):
        register_abort()
        self.scrape_batch.return_value = {**_STATS, "scraped": 0, "unavailable": 2}

        scrape_pending_videos(max_videos=5)

        self.assertIsNone(get_cooldown())

    @override_settings(TIKTOK_SCRAPER_ENABLED=True)
    def test_run_without_any_answer_keeps_the_abort_count(self):
        register_abort()
        self.scrape_batch.return_value = {**_STATS, "scraped": 0}

        scrape_pending_videos(max_videos=5)

        self.assertEqual(get_cooldown()["consecutive_aborts"], 1)

    @override_settings(TIKTOK_SCRAPER_ENABLED=True)
    def test_soft_time_limit_releases_lock(self):
        self.scrape_batch.side_effect = SoftTimeLimitExceeded()

        with patch("ddcs.metadata.scraper.tasks.recover_db_connection") as recover:
            self.assertIsNone(scrape_pending_videos())

        recover.assert_called_once_with()
        self.lock.release.assert_called_once_with()


_COMMAND = "ddcs.metadata.management.commands.enqueue_watched_videos"


class EnqueueWatchedVideosCommandTests(TestCase):
    def setUp(self):
        self.early = datetime(2026, 7, 5, 10, tzinfo=UTC)
        self.late = datetime(2026, 8, 5, 10, tzinfo=UTC)
        self.outside = datetime(2026, 10, 5, 10, tzinfo=UTC)
        # Watch history per participant; an Exception stands for a donation
        # that cannot be decrypted.
        self.histories: dict[str, list | Exception] = {
            "anna": [
                _view(1, self.early),
                _view(1, self.early),
                _view(2, self.outside),
            ],
            "ben": [_view(1, self.late), _view(3, self.early), _view(None, self.early)],
        }

    def _call(self, *args: str) -> str:
        participants = [Mock(pk=name) for name in self.histories]

        def watch_history(participant: Mock) -> list:
            history = self.histories[participant.pk]
            if isinstance(history, Exception):
                raise history
            return history

        out = StringIO()
        with (
            patch(f"{_COMMAND}.participants_with_watch_history") as with_history,
            patch(f"{_COMMAND}.get_watch_history", side_effect=watch_history),
        ):
            with_history.return_value.iterator.return_value = iter(participants)
            call_command("enqueue_watched_videos", *args, stdout=out)
        return out.getvalue()

    def test_counts_donors_and_keeps_the_latest_view(self):
        out = self._call()

        # Video 1: two donors (Anna's repeat view counts once), last seen by Ben.
        self.assertEqual(_ranking(1), (2, self.late))
        self.assertEqual(_ranking(3), (1, self.early))
        # Video 2 was only watched outside the window.
        self.assertFalse(ScrapeTarget.objects.filter(video__id_tiktok=2).exists())
        self.assertIn("Donations read: 2", out)
        self.assertIn("Views in the window: 4", out)
        self.assertIn("Records skipped (no date or no video ID): 1", out)
        # Anna watched video 1; Ben watched videos 1 and 3.
        self.assertIn("Videos watched in the window, summed over donations: 3", out)
        self.assertIn("Counts reset on existing targets: 0", out)
        self.assertIn("Targets created: 2", out)
        self.assertIn("Counts raised on existing targets: 1", out)

    def test_each_donation_is_written_before_the_next_is_read(self):
        seen_before_ben = []

        def watch_history(participant: Mock) -> list:
            if participant.pk == "ben":
                seen_before_ben.append(ScrapeTarget.objects.count())
            return self.histories[participant.pk]

        with (
            patch(f"{_COMMAND}.participants_with_watch_history") as with_history,
            patch(f"{_COMMAND}.get_watch_history", side_effect=watch_history),
        ):
            with_history.return_value.iterator.return_value = iter(
                [Mock(pk="anna"), Mock(pk="ben")]
            )
            call_command("enqueue_watched_videos", stdout=StringIO())

        # Anna's video was already queued when Ben's history was read.
        self.assertEqual(seen_before_ben, [1])

    def test_rerun_counts_from_scratch(self):
        self._call()

        out = self._call()

        self.assertEqual(_ranking(1), (2, self.late))
        self.assertEqual(_ranking(3), (1, self.early))
        self.assertIn("Counts reset on existing targets: 2", out)
        self.assertIn("Targets created: 0", out)

    def test_rerun_corrects_counts_added_by_incoming_donations(self):
        self._call()
        # E.g. a retried donation counted twice.
        enqueue_watched_videos({1: (1, self.late)})
        self.assertEqual(_ranking(1)[0], 3)

        self._call()

        self.assertEqual(_ranking(1), (2, self.late))

    def test_keep_counts_adds_on_top(self):
        self._call()

        out = self._call("--keep-counts")

        self.assertEqual(_ranking(1), (4, self.late))
        self.assertEqual(_ranking(3), (2, self.early))
        self.assertNotIn("Counts reset", out)

    def test_targets_no_view_backs_any_more_drop_to_zero(self):
        self._call()
        del self.histories["ben"]

        self._call()

        self.assertEqual(_ranking(1), (1, self.early))
        self.assertEqual(_ranking(3), (0, None))

    def test_rerun_does_not_requeue_scraped_videos(self):
        self._call()
        ScrapeTarget.objects.filter(video__id_tiktok=1).update(
            status=Status.SUCCESS, attempts=1
        )

        self._call()

        target = ScrapeTarget.objects.get(video__id_tiktok=1)
        self.assertEqual((target.status, target.attempts), (Status.SUCCESS, 1))
        self.assertEqual(target.occurrence_count, 2)

    def test_videos_covered_by_the_research_api_are_reported_not_queued(self):
        APIVideoInfos.objects.create(video=_video(1))

        out = self._call()

        # Both Anna and Ben watched video 1: skipped once per donation.
        self.assertIn("Skipped, Research API has the video (per donation): 2", out)
        self.assertFalse(ScrapeTarget.objects.filter(video__id_tiktok=1).exists())

    def test_unreadable_donation_is_skipped_and_reported(self):
        self.histories["carl"] = ValueError("cannot decrypt")

        with self.assertLogs(_COMMAND, level="ERROR"):
            out = self._call()

        self.assertIn("Donations read: 2", out)
        self.assertIn("Donations that could not be read: 1", out)
        self.assertEqual(_ranking(1), (2, self.late))

    def test_custom_window(self):
        self._call("--start", "2026-10-01", "--end", "2026-10-31")

        self.assertEqual(
            set(ScrapeTarget.objects.values_list("video__id_tiktok", flat=True)), {2}
        )

    def test_start_after_end_is_rejected(self):
        with self.assertRaises(CommandError):
            self._call("--start", "2026-09-01", "--end", "2026-08-01")

    def test_dry_run_changes_nothing_not_even_existing_counts(self):
        enqueue_watched_videos({7: (5, self.late)})

        out = self._call("--dry-run")

        self.assertIn("Videos watched in the window, summed over donations: 3", out)
        self.assertIn("Dry run: nothing was changed.", out)
        self.assertNotIn("Targets created", out)
        self.assertEqual(_ranking(7), (5, self.late))
        self.assertEqual(ScrapeTarget.objects.count(), 1)
        self.assertEqual(TikTokVideo.objects.count(), 1)


@skipUnless(
    os.environ.get("TIKTOK_LIVE_TESTS"),
    "Sends real requests to tiktok.com; set TIKTOK_LIVE_TESTS=1 to run.",
)
class ScraperServiceLiveTests(TestCase):
    def test_scrapes_existing_video_and_marks_missing_one_unavailable(self):
        existing = _video(7470493179767344430)
        missing = _video(7000000000000000001)
        enqueue_videos([existing.id_tiktok, missing.id_tiktok])

        stats = ScraperService(scraper=TikTokScraper(rate_delay=1.0)).scrape_batch(
            limit=10
        )

        self.assertEqual((stats["scraped"], stats["unavailable"]), (1, 1), stats)
        infos = VideoInfosScraped.objects.get(video=existing)
        self.assertTrue(infos.description)
        self.assertIsNotNone(infos.create_time)
        self.assertIsNotNone(VideoStatisticsScraped.objects.get().view_count)
        existing.refresh_from_db()
        self.assertEqual(existing.user.name, "tiktok")
        target = ScrapeTarget.objects.get(video=missing)
        self.assertEqual(target.status, Status.UNAVAILABLE)
        self.assertIsNotNone(target.tiktok_status_code)

    def test_stores_original_language_caption(self):
        # A German video that had a caption when this test was written.
        video = _video(7652127324279721249)
        enqueue_videos([video.id_tiktok])

        stats = ScraperService(
            scraper=TikTokScraper(rate_delay=1.0), fetch_captions=True
        ).scrape_batch(limit=10)

        self.assertEqual((stats["scraped"], stats["captions_fetched"]), (1, 1), stats)
        infos = VideoInfosScraped.objects.get(video=video)
        self.assertEqual(infos.caption_status, CaptionStatus.FETCHED)
        self.assertTrue(infos.caption_vtt.startswith("WEBVTT"))
        self.assertTrue(infos.voice_to_text)
        self.assertNotIn("-->", infos.voice_to_text)
        self.assertEqual(infos.caption_language, "deu-DE")
