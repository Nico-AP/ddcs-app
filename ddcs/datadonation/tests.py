from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from django.test import TestCase

from ddcs.core.types import TikTokUserData
from ddcs.datadonation import services
from ddcs.datadonation.config import (
    FOLLOWED_BP_NAME,
    LIKED_VIDEOS_BP_NAME,
    WATCH_HISTORY_BP_NAME,
)
from ddcs.datadonation.services import (
    _add_video_id_to_record,
    _clean_donated_data,
    _clean_record,
    _clean_records,
    _extract_id_from_link,
    _get_decryptor,
    _map_to_user_data,
    _normalise_key,
    _normalise_value,
    _parse_date,
    get_user_data,
    post_process_donation,
)


class NormaliseKeyTests(TestCase):
    def test_lowercases_key(self):
        self.assertEqual(_normalise_key("USERNAME"), "username")

    def test_resolves_date_variant(self):
        self.assertEqual(_normalise_key("(D|d)ate"), "date")

    def test_resolves_link_variant(self):
        self.assertEqual(_normalise_key("(L|l)ink"), "link")

    def test_passes_through_already_lowercased_known(self):
        self.assertEqual(_normalise_key("date"), "date")
        self.assertEqual(_normalise_key("link"), "link")

    def test_passes_through_unknown_key(self):
        self.assertEqual(_normalise_key("Foo"), "foo")


class ParseDateTests(TestCase):
    def test_parses_standard_format(self):
        result = _parse_date("2026-05-08 13:15:38")
        self.assertEqual(result, datetime(2026, 5, 8, 13, 15, 38, tzinfo=UTC))

    def test_parses_format_with_utc_suffix(self):
        result = _parse_date("2026-05-08 13:15:38 UTC")
        self.assertEqual(result, datetime(2026, 5, 8, 13, 15, 38, tzinfo=UTC))

    def test_returns_original_string_on_unknown_format(self):
        self.assertEqual(_parse_date("not a date"), "not a date")

    def test_strips_surrounding_whitespace(self):
        result = _parse_date("  2026-05-08 13:15:38  ")
        self.assertEqual(result, datetime(2026, 5, 8, 13, 15, 38, tzinfo=UTC))

    def test_parses_iso_format_without_tz_as_utc(self):
        result = _parse_date("2026-05-08T13:15:38")
        self.assertEqual(result, datetime(2026, 5, 8, 13, 15, 38, tzinfo=UTC))

    def test_parses_iso_format_with_explicit_offset(self):
        result = _parse_date("2026-05-08T13:15:38+02:00")
        self.assertEqual(result.utcoffset().total_seconds(), 7200)

    def test_does_not_mangle_value_ending_in_utc_chars(self):
        # Guards against the old rstrip(" UTC") bug, which stripped trailing
        # digits like the "8" in ":38" because rstrip strips a char set.
        result = _parse_date("2026-05-08 13:15:38")
        self.assertEqual(result, datetime(2026, 5, 8, 13, 15, 38, tzinfo=UTC))

    def test_returns_original_value_unchanged_not_stripped(self):
        self.assertEqual(_parse_date("  bogus  "), "  bogus  ")


class NormaliseValueTests(TestCase):
    def test_parses_date_value_for_date_key(self):
        result = _normalise_value("date", "2026-05-08 13:15:38")
        self.assertEqual(result, datetime(2026, 5, 8, 13, 15, 38, tzinfo=UTC))

    def test_returns_non_string_date_unchanged(self):
        dt = datetime(2026, 5, 8, tzinfo=UTC)
        self.assertIs(_normalise_value("date", dt), dt)

    def test_returns_value_unchanged_for_non_date_key(self):
        self.assertEqual(
            _normalise_value("link", "https://tiktok.com/@a/video/1"),
            "https://tiktok.com/@a/video/1",
        )


class CleanRecordTests(TestCase):
    def test_normalises_keys_and_date_value(self):
        record = {
            "(D|d)ate": "2026-05-08 13:15:38",
            "(L|l)ink": "https://www.tiktok.com/@x/video/123",
        }
        result = _clean_record(record)
        self.assertEqual(
            result,
            {
                "date": datetime(2026, 5, 8, 13, 15, 38, tzinfo=UTC),
                "link": "https://www.tiktok.com/@x/video/123",
            },
        )

    def test_handles_empty_record(self):
        self.assertEqual(_clean_record({}), {})


class CleanRecordsTests(TestCase):
    def test_returns_none_for_none_input(self):
        self.assertIsNone(_clean_records(None))

    def test_returns_empty_list_for_empty_input(self):
        self.assertEqual(_clean_records([]), [])

    def test_cleans_each_record(self):
        records = [
            {"Date": "2026-05-08 13:15:38"},
            {"Link": "https://tiktok.com/@x/video/9"},
        ]
        result = _clean_records(records)
        self.assertEqual(
            result,
            [
                {"date": datetime(2026, 5, 8, 13, 15, 38, tzinfo=UTC)},
                {"link": "https://tiktok.com/@x/video/9"},
            ],
        )


class CleanDonatedDataTests(TestCase):
    def test_cleans_records_per_blueprint(self):
        data = {
            WATCH_HISTORY_BP_NAME: [{"Date": "2026-05-08 13:15:38"}],
            FOLLOWED_BP_NAME: None,
            LIKED_VIDEOS_BP_NAME: [],
        }
        result = _clean_donated_data(data)
        self.assertEqual(
            result[WATCH_HISTORY_BP_NAME],
            [{"date": datetime(2026, 5, 8, 13, 15, 38, tzinfo=UTC)}],
        )
        self.assertIsNone(result[FOLLOWED_BP_NAME])
        self.assertEqual(result[LIKED_VIDEOS_BP_NAME], [])

    def test_logs_summary_when_dates_unparseable(self):
        data = {
            WATCH_HISTORY_BP_NAME: [
                {"Date": "2026-05-08 13:15:38"},
                {"Date": "bogus"},
                {"Date": "also bogus"},
            ],
            FOLLOWED_BP_NAME: None,
            LIKED_VIDEOS_BP_NAME: None,
        }
        with self.assertLogs("ddcs.datadonation.services", level="WARNING") as cm:
            _clean_donated_data(data)
        self.assertEqual(len(cm.records), 1)
        self.assertIn("2", cm.records[0].getMessage())

    def test_does_not_log_when_all_dates_parse(self):
        data = {
            WATCH_HISTORY_BP_NAME: [{"Date": "2026-05-08 13:15:38"}],
            FOLLOWED_BP_NAME: None,
            LIKED_VIDEOS_BP_NAME: None,
        }
        logger_name = "ddcs.datadonation.services"
        with self.assertNoLogs(logger_name, level="WARNING"):
            _clean_donated_data(data)


class ExtractIdFromLinkTests(TestCase):
    def test_extracts_trailing_id(self):
        self.assertEqual(
            _extract_id_from_link(
                "https://www.tiktok.com/@user/video/7100000000000000001"
            ),
            7100000000000000001,
        )

    def test_strips_trailing_slash(self):
        self.assertEqual(
            _extract_id_from_link("https://www.tiktok.com/@user/video/12345/"),
            12345,
        )

    def test_returns_none_when_trailing_segment_not_int(self):
        self.assertIsNone(
            _extract_id_from_link("https://www.tiktok.com/@user/video/abc")
        )

    def test_returns_none_for_empty_string(self):
        self.assertIsNone(_extract_id_from_link(""))


class AddVideoIdToRecordTests(TestCase):
    def test_adds_video_id_when_link_present(self):
        record = {"link": "https://www.tiktok.com/@user/video/42"}
        result = _add_video_id_to_record(record)
        self.assertEqual(result, {"link": record["link"], "video_id": 42})

    def test_video_id_is_none_when_link_unparseable(self):
        record = {"link": "https://www.tiktok.com/@user/video/abc"}
        result = _add_video_id_to_record(record)
        self.assertEqual(result["video_id"], None)

    def test_returns_record_unchanged_when_no_link(self):
        record = {"date": "2026-05-08 13:15:38"}
        result = _add_video_id_to_record(record)
        self.assertEqual(result, record)
        self.assertNotIn("video_id", result)

    def test_does_not_mutate_input(self):
        record = {"link": "https://www.tiktok.com/@user/video/7"}
        _add_video_id_to_record(record)
        self.assertNotIn("video_id", record)


class MapToUserDataTests(TestCase):
    def test_maps_all_blueprints_and_adds_video_ids(self):
        data = {
            WATCH_HISTORY_BP_NAME: [
                {"link": "https://www.tiktok.com/@x/video/1"},
            ],
            FOLLOWED_BP_NAME: [{"username": "alice"}],
            LIKED_VIDEOS_BP_NAME: [
                {"link": "https://www.tiktok.com/@x/video/2"},
            ],
        }
        result = _map_to_user_data(data)
        self.assertIsInstance(result, TikTokUserData)
        self.assertEqual(
            result.watch_history,
            [
                {"link": "https://www.tiktok.com/@x/video/1", "video_id": 1},
            ],
        )
        self.assertEqual(result.followed_accounts, [{"username": "alice"}])
        self.assertEqual(
            result.liked_videos,
            [
                {"link": "https://www.tiktok.com/@x/video/2", "video_id": 2},
            ],
        )

    def test_handles_missing_blueprints_as_none(self):
        result = _map_to_user_data({})
        self.assertIsNone(result.watch_history)
        self.assertIsNone(result.followed_accounts)
        self.assertIsNone(result.liked_videos)

    def test_preserves_none_blueprint_values(self):
        data = {
            WATCH_HISTORY_BP_NAME: None,
            FOLLOWED_BP_NAME: None,
            LIKED_VIDEOS_BP_NAME: None,
        }
        result = _map_to_user_data(data)
        self.assertIsNone(result.watch_history)
        self.assertIsNone(result.followed_accounts)
        self.assertIsNone(result.liked_videos)


class GetDecryptorTests(TestCase):
    def setUp(self):
        services._DECRYPTORS.clear()

    @patch("ddcs.datadonation.services.Decryption")
    def test_caches_decryptor_per_project(self, mock_decryption):
        project = MagicMock(pk=1, secret="s")
        project.get_salt.return_value = "salt"

        first = _get_decryptor(project)
        second = _get_decryptor(project)

        self.assertIs(first, second)
        mock_decryption.assert_called_once_with("s", "salt")

    @patch("ddcs.datadonation.services.Decryption")
    def test_caches_separately_for_different_projects(self, mock_decryption):
        mock_decryption.side_effect = lambda *_a, **_kw: MagicMock()
        p1 = MagicMock(pk=1, secret="s1")
        p1.get_salt.return_value = "salt1"
        p2 = MagicMock(pk=2, secret="s2")
        p2.get_salt.return_value = "salt2"

        d1 = _get_decryptor(p1)
        d2 = _get_decryptor(p2)

        self.assertIsNot(d1, d2)
        self.assertEqual(mock_decryption.call_count, 2)


class GetUserDataTests(TestCase):
    @patch("ddcs.datadonation.services._get_donation_data")
    def test_pipeline_cleans_and_maps_data(self, mock_get_donation_data):
        mock_get_donation_data.return_value = {
            WATCH_HISTORY_BP_NAME: [
                {
                    "Date": "2026-05-08 13:15:38",
                    "Link": "https://www.tiktok.com/@x/video/7",
                },
            ],
            FOLLOWED_BP_NAME: None,
            LIKED_VIDEOS_BP_NAME: None,
        }
        participant = MagicMock()

        result = get_user_data(participant)

        mock_get_donation_data.assert_called_once_with(participant)
        self.assertIsInstance(result, TikTokUserData)
        self.assertEqual(
            result.watch_history,
            [
                {
                    "date": datetime(2026, 5, 8, 13, 15, 38, tzinfo=UTC),
                    "link": "https://www.tiktok.com/@x/video/7",
                    "video_id": 7,
                }
            ],
        )
        self.assertIsNone(result.followed_accounts)
        self.assertIsNone(result.liked_videos)


class PostProcessDonationTests(TestCase):
    @patch("ddcs.datadonation.services.generate_report_statistics")
    @patch("ddcs.datadonation.services.register_donation_metadata")
    @patch("ddcs.datadonation.services.get_user_data")
    def test_runs_pipeline_in_order(
        self, mock_get_user_data, mock_register, mock_generate
    ):
        participant = MagicMock()
        user_data = TikTokUserData()
        mock_get_user_data.return_value = user_data

        post_process_donation(participant)

        mock_get_user_data.assert_called_once_with(participant)
        mock_register.assert_called_once_with(user_data)
        mock_generate.assert_called_once_with(participant, user_data)
