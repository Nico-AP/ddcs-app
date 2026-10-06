import os
from unittest import skipUnless
from unittest.mock import Mock, call, patch

import requests
from django.test import SimpleTestCase

from ddcs.metadata.scraper.client import TikTokClient
from ddcs.metadata.scraper.config import MAIN_URL, REQUEST_TIMEOUT
from ddcs.metadata.scraper.exceptions import (
    TikTokBlockedError,
    TikTokClientGetError,
    TikTokDataExtractionError,
    TikTokItemUnavailableError,
    TikTokMissingRehydrationDataError,
    TikTokRehydrationDataAttributeError,
)
from ddcs.metadata.scraper.parsers import TikTokParser
from ddcs.metadata.scraper.scraper import TikTokScraper
from ddcs.metadata.scraper.utils import int_or_none

TEST_VIDEO_ID = "7470493179767344430"
TEST_CREATOR_NAME = "tiktok"

_SLEEP = "ddcs.metadata.scraper.scraper.time.sleep"
_MONOTONIC = "ddcs.metadata.scraper.scraper.time.monotonic"
_UNIFORM = "ddcs.metadata.scraper.scraper.random.uniform"


def _response(status_code: int = 200, text: str = "") -> Mock:
    return Mock(status_code=status_code, ok=status_code < 400, text=text)


def _page(payload: str) -> str:
    return (
        "<html><head>"
        '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">'
        f"{payload}</script></head></html>"
    )


_VIDEO_PAGE = _page(
    '{"__DEFAULT_SCOPE__": {"webapp.video-detail": '
    '{"itemInfo": {"itemStruct": {"id": "123"}}}}}'
)
_USER_PAGE = _page(
    '{"__DEFAULT_SCOPE__": {"webapp.user-detail": '
    '{"userInfo": {"user": {"uniqueId": "name"}}}}}'
)


class TikTokClientTests(SimpleTestCase):
    def setUp(self):
        self.session = Mock()
        self.session.headers = {}
        self.session.get.return_value = _response()
        self.client = TikTokClient(session=self.session)

    def test_creating_a_client_sends_no_request(self):
        self.session.get.assert_not_called()

    def test_first_get_fetches_cookies_from_main_page_once(self):
        self.client.get("https://example.com/a")
        self.client.get("https://example.com/b")

        self.assertEqual(
            self.session.get.call_args_list,
            [
                call(MAIN_URL, timeout=REQUEST_TIMEOUT),
                call("https://example.com/a", timeout=REQUEST_TIMEOUT),
                call("https://example.com/b", timeout=REQUEST_TIMEOUT),
            ],
        )

    def test_reset_session_clears_cookies_and_fetches_new_ones(self):
        self.client.get("https://example.com/a")
        self.client.reset_session()
        self.client.get("https://example.com/b")

        self.session.cookies.clear.assert_called_once_with()
        urls = [c.args[0] for c in self.session.get.call_args_list]
        self.assertEqual(
            urls, [MAIN_URL, "https://example.com/a", MAIN_URL, "https://example.com/b"]
        )

    def test_connection_errors_and_timeouts_raise_get_error(self):
        for error in (requests.ConnectionError("down"), requests.Timeout("slow")):
            with self.subTest(error=error):
                self.session.get.side_effect = error
                with self.assertRaises(TikTokClientGetError):
                    self.client.get("https://example.com/a")

    def test_403_and_429_raise_blocked_error(self):
        for status in (403, 429):
            with self.subTest(status=status):
                self.session.get.return_value = _response(status)
                with self.assertRaises(TikTokBlockedError):
                    self.client.get("https://example.com/a")

    def test_other_error_status_raises_get_error_but_not_blocked(self):
        self.session.get.return_value = _response(500)

        with self.assertRaises(TikTokClientGetError) as ctx:
            self.client.get("https://example.com/a")

        self.assertNotIsInstance(ctx.exception, TikTokBlockedError)


class TikTokParserTests(SimpleTestCase):
    def test_load_rehydration_data(self):
        test_response = """
        <h1> Test Data</h1>
        <script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">{"test": 123}</script>
        """
        hydr_data = TikTokParser.load_rehydration_data(test_response)
        self.assertEqual(hydr_data["test"], 123)

    def test_load_rehydration_data_ignores_other_scripts(self):
        test_response = (
            '<script id="other">{"other": 1}</script>' + _page('{"test": 123}')
        ) + "<script>var x = 1;</script>"
        hydr_data = TikTokParser.load_rehydration_data(test_response)
        self.assertEqual(hydr_data, {"test": 123})

    def test_load_rehydration_data_missing_script(self):
        test_response = """
        <h1> Test Data</h1>
        <script id="__DATA_FOR_REHYDRATION__">{"test": 123}</script>
        """
        with self.assertRaises(TikTokMissingRehydrationDataError):
            TikTokParser.load_rehydration_data(test_response)

    def test_load_rehydration_data_empty_or_invalid_script(self):
        for payload in ("", "{not json"):
            with (
                self.subTest(payload=payload),
                self.assertRaises(TikTokRehydrationDataAttributeError),
            ):
                TikTokParser.load_rehydration_data(_page(payload))

    def test_extract_video_data_with_valid_data(self):
        example_data = {
            "__DEFAULT_SCOPE__": {
                "webapp.video-detail": {
                    "itemInfo": {
                        "itemStruct": "some data",
                    },
                },
            },
        }
        data = TikTokParser.extract_video_data(example_data)
        self.assertEqual(data, "some data")

    def test_extract_video_data_with_invalid_data(self):
        example_data = {
            "__DEFAULT_SCOPE__": {
                "webapp.video-detail": {
                    "itemInfo": {
                        "missingKey": None,
                    },
                },
            },
        }
        with self.assertRaises(TikTokDataExtractionError) as ctx:
            TikTokParser.extract_video_data(example_data)
        self.assertNotIsInstance(ctx.exception, TikTokItemUnavailableError)

    def test_extract_video_data_with_status_code_raises_unavailable(self):
        example_data = {
            "__DEFAULT_SCOPE__": {
                "webapp.video-detail": {
                    "statusCode": 10204,
                    "statusMsg": "item doesn't exist",
                },
            },
        }
        with self.assertRaises(TikTokItemUnavailableError) as ctx:
            TikTokParser.extract_video_data(example_data)
        self.assertEqual(ctx.exception.status_code, 10204)
        self.assertEqual(ctx.exception.status_msg, "item doesn't exist")

    def test_extract_user_data_with_valid_data(self):
        example_data = {
            "__DEFAULT_SCOPE__": {
                "webapp.user-detail": {
                    "userInfo": {"user": "some data"},
                },
            },
        }
        data = TikTokParser.extract_user_data(example_data)
        self.assertEqual(data, {"user": "some data"})

    def test_extract_user_data_with_invalid_data(self):
        example_data = {"__DEFAULT_SCOPE__": {"webapp.video-detail": {}}}
        with self.assertRaises(TikTokDataExtractionError):
            TikTokParser.extract_user_data(example_data)


_VTT = """WEBVTT


00:00:00.400 --> 00:00:01.600
Hallo zusammen

1
00:00:02.200 --> 00:00:03.520 align:start
heute geht es um
<c.yellow>die Wahl</c>

NOTE this is a comment

00:00:04.720 --> 00:00:06.400
und um  mehr
"""

_ORIGINAL_CAPTION = {
    "language": "deu-DE",
    "url": "https://cdn.example/original.vtt",
    "captionFormat": "webvtt",
    "isAutoGen": False,
    "isOriginalCaption": True,
}
_TRANSLATED_CAPTION = {
    "language": "eng-US",
    "url": "https://cdn.example/translation.vtt",
    "captionFormat": "webvtt",
    "isAutoGen": True,
    "isOriginalCaption": False,
}


def _video_with_captions(*captions: dict) -> dict:
    return {"id": "123", "video": {"claInfo": {"captionInfos": list(captions)}}}


class TikTokCaptionParserTests(SimpleTestCase):
    def test_selects_the_original_caption_not_the_translation(self):
        data = _video_with_captions(_TRANSLATED_CAPTION, _ORIGINAL_CAPTION)

        self.assertEqual(TikTokParser.select_original_caption(data), _ORIGINAL_CAPTION)

    def test_no_original_caption(self):
        for data in (
            {"id": "123"},
            {"id": "123", "video": {}},
            {"id": "123", "video": {"claInfo": {"captionInfos": []}}},
            _video_with_captions(_TRANSLATED_CAPTION),
        ):
            with self.subTest(data=data):
                self.assertIsNone(TikTokParser.select_original_caption(data))

    def test_ignores_original_caption_in_another_format_or_without_url(self):
        other_format = {**_ORIGINAL_CAPTION, "captionFormat": "creator_caption"}
        without_url = {**_ORIGINAL_CAPTION, "url": ""}

        data = _video_with_captions(other_format, without_url)

        self.assertIsNone(TikTokParser.select_original_caption(data))

    def test_webvtt_to_text_keeps_only_the_spoken_text(self):
        self.assertEqual(
            TikTokParser.webvtt_to_text(_VTT),
            "Hallo zusammen heute geht es um die Wahl und um mehr",
        )

    def test_webvtt_to_text_handles_windows_line_endings_and_empty_files(self):
        self.assertEqual(
            TikTokParser.webvtt_to_text(_VTT.replace("\n", "\r\n")),
            "Hallo zusammen heute geht es um die Wahl und um mehr",
        )
        self.assertEqual(TikTokParser.webvtt_to_text("WEBVTT\n"), "")
        self.assertEqual(TikTokParser.webvtt_to_text(""), "")


class TikTokScraperTests(SimpleTestCase):
    def setUp(self):
        self.client = Mock()
        self.scraper = TikTokScraper(rate_delay=1.0, client=self.client)

    def test_get_video_url(self):
        url = TikTokScraper.get_video_url("123")
        self.assertEqual(url, "https://www.tiktok.com/@tiktok/video/123")

    def test_get_user_url(self):
        url = TikTokScraper.get_user_url("123")
        self.assertEqual(url, "https://www.tiktok.com/@123")

    def test_scrape_video_requests_video_url(self):
        self.client.get.return_value = _response(text=_VIDEO_PAGE)

        data = self.scraper.scrape_video("123")

        self.client.get.assert_called_once_with(
            "https://www.tiktok.com/@tiktok/video/123"
        )
        self.assertEqual(data, {"id": "123"})

    def test_scrape_user_requests_user_url(self):
        self.client.get.return_value = _response(text=_USER_PAGE)

        data = self.scraper.scrape_user("name")

        self.client.get.assert_called_once_with("https://www.tiktok.com/@name")
        self.assertEqual(data, {"user": {"uniqueId": "name"}})

    def test_video_list_yields_success_and_typed_error_results(self):
        self.client.get.side_effect = [
            _response(text=_VIDEO_PAGE),
            _response(text="<html>no data</html>"),
        ]

        with patch(_SLEEP):
            results = list(self.scraper.scrape_video_list(["1", "2"]))

        self.assertEqual(
            results[0], {"success": True, "data": {"id": "123"}, "video_id": "1"}
        )
        self.assertFalse(results[1]["success"])
        self.assertEqual(results[1]["video_id"], "2")
        self.assertEqual(results[1]["error_type"], "TikTokMissingRehydrationDataError")
        self.assertTrue(results[1]["error"])

    def _sleeps_for_requests_at(self, *times: float, scrape_list=None) -> list:
        """Sleep calls made when one item is requested at each given time."""
        self.client.get.return_value = _response(text=_USER_PAGE)
        scrape_list = scrape_list or self.scraper.scrape_user_list
        with patch(_SLEEP) as sleep, patch(_MONOTONIC, side_effect=times):
            list(scrape_list([str(i) for i in range(len(times))]))
        return sleep.call_args_list

    def test_first_request_is_not_delayed(self):
        self.assertEqual(self._sleeps_for_requests_at(100.0), [])

    def test_requests_start_at_least_rate_delay_apart(self):
        for scrape_list in (
            self.scraper.scrape_video_list,
            self.scraper.scrape_user_list,
        ):
            with self.subTest(scrape_list=scrape_list):
                scraper = TikTokScraper(rate_delay=1.0, client=self.client)
                self.scraper = scraper
                # Second item is ready 0.3 s after the first request started,
                # the third right when its slot opens (2.0 after two waits).
                sleeps = self._sleeps_for_requests_at(
                    100.0,
                    100.3,
                    101.0,
                    scrape_list=getattr(scraper, scrape_list.__name__),
                )
                self.assertEqual(len(sleeps), 2)
                self.assertAlmostEqual(sleeps[0].args[0], 0.7)
                self.assertAlmostEqual(sleeps[1].args[0], 1.0)

    def test_time_spent_since_the_last_request_counts_towards_the_delay(self):
        # The second item only comes 5 s later: nothing left to wait for.
        self.assertEqual(self._sleeps_for_requests_at(100.0, 105.0), [])

    def test_jitter_varies_the_interval_around_the_delay(self):
        self.scraper = TikTokScraper(
            rate_delay=2.0, client=self.client, rate_jitter=0.3
        )

        # Each interval is 2.0 s times the factor drawn for it.
        with patch(_UNIFORM, side_effect=[0.75, 1.25, 1.0]) as uniform:
            sleeps = self._sleeps_for_requests_at(100.0, 100.0, 101.5)

        uniform.assert_called_with(0.7, 1.3)
        self.assertEqual(len(sleeps), 2)
        # Slot 2 opens at 100 + 2.0 * 0.75; slot 3 at 101.5 + 2.0 * 1.25.
        self.assertAlmostEqual(sleeps[0].args[0], 1.5)
        self.assertAlmostEqual(sleeps[1].args[0], 2.5)

    def test_without_jitter_no_randomness_is_involved(self):
        with patch(_UNIFORM) as uniform:
            self._sleeps_for_requests_at(100.0, 100.0)

        uniform.assert_not_called()

    def test_no_delay_configured(self):
        self.scraper = TikTokScraper(rate_delay=0, client=self.client)

        self.assertEqual(self._sleeps_for_requests_at(100.0, 100.0, 100.0), [])

    def test_blocked_item_is_retried_once_with_a_fresh_session(self):
        self.client.get.side_effect = [
            TikTokBlockedError("blocked"),
            _response(text=_VIDEO_PAGE),
        ]

        with patch(_SLEEP):
            results = list(self.scraper.scrape_video_list(["1"]))

        self.client.reset_session.assert_called_once_with()
        self.assertTrue(results[0]["success"])

    def test_item_blocked_twice_yields_blocked_error(self):
        self.client.get.side_effect = TikTokBlockedError("blocked")

        with patch(_SLEEP):
            results = list(self.scraper.scrape_video_list(["1"]))

        self.assertEqual(self.client.get.call_count, 2)
        self.assertEqual(results[0]["error_type"], "TikTokBlockedError")

    def test_fetch_original_caption_downloads_it_without_delay(self):
        self.client.get.return_value = _response(text=_VTT)
        data = _video_with_captions(_TRANSLATED_CAPTION, _ORIGINAL_CAPTION)

        with patch(_SLEEP) as sleep:
            caption = self.scraper.fetch_original_caption(data)

        sleep.assert_not_called()
        self.client.get.assert_called_once_with("https://cdn.example/original.vtt")
        self.assertEqual(
            caption, {"language": "deu-DE", "is_auto_generated": False, "vtt": _VTT}
        )

    def test_caption_delay_pauses_before_the_download(self):
        self.client.get.return_value = _response(text=_VTT)
        scraper = TikTokScraper(rate_delay=1.0, client=self.client, caption_delay=0.5)

        with patch(_SLEEP) as sleep:
            scraper.fetch_original_caption(_video_with_captions(_ORIGINAL_CAPTION))

        sleep.assert_called_once_with(0.5)

    def test_fetch_original_caption_without_caption_sends_no_request(self):
        with patch(_SLEEP) as sleep:
            caption = self.scraper.fetch_original_caption({"id": "123"})

        self.assertIsNone(caption)
        sleep.assert_not_called()
        self.client.get.assert_not_called()

    def test_fetch_original_caption_passes_download_errors_on(self):
        self.client.get.side_effect = TikTokClientGetError("gone")

        with patch(_SLEEP), self.assertRaises(TikTokClientGetError):
            self.scraper.fetch_original_caption(_video_with_captions(_ORIGINAL_CAPTION))

    def test_programming_errors_are_not_swallowed(self):
        self.client.get.side_effect = KeyError("bug")

        with self.assertRaises(KeyError):
            list(self.scraper.scrape_video_list(["1"]))


@skipUnless(
    os.environ.get("TIKTOK_LIVE_TESTS"),
    "Sends real requests to tiktok.com; set TIKTOK_LIVE_TESTS=1 to run.",
)
class TikTokLiveTests(SimpleTestCase):
    def test_scrape_video(self):
        data = TikTokScraper().scrape_video(TEST_VIDEO_ID)

        self.assertIn("id", data)
        self.assertIn("video", data)

    def test_scrape_user(self):
        data = TikTokScraper().scrape_user(TEST_CREATOR_NAME)

        self.assertIn("user", data)


class UtilsTests(SimpleTestCase):
    def test_int_or_none(self):
        self.assertIsNone(int_or_none(None))
        self.assertIsNone(int_or_none("abc"))
        self.assertEqual(int_or_none(True), 1)
        self.assertEqual(int_or_none(1.3), 1)
