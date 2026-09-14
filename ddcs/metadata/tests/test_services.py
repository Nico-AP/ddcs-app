from datetime import UTC, datetime
from unittest.mock import patch

import httpx
from django.test import TestCase, override_settings

from ddcs.metadata.models import DataOrigins, TikTokVideo, TikTokVideoClassification
from ddcs.metadata.services import ZuseAPIClient


def make_zuse_result(id_tiktok: int, **overrides) -> dict:
    """Sample Zuse API result payload, with optional field overrides."""
    result = {
        "id_tiktok": id_tiktok,
        "predictions": {
            "is_political": True,
            "political_other": False,
            "political_content": True,
            "stage1_rationale": "mentions an election",
            "entities": ["Senator Smith"],
            "keyword_matches": ["election"],
            "language": "en",
            "plausible_party": "PartyX",
            "created_at": datetime(2026, 9, 9, tzinfo=UTC).isoformat(),
        },
        "entities": [{"sentiment": "positive"}, {"sentiment": None}],
        "extended": {"raw": "data"},
        "media": {"thumbnail": "https://zuse.example.com/thumb/1.jpg"},
        "predictions_div": {"is_political": False},
    }
    result.update(overrides)
    return result


def make_response(json_data: dict, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=json_data,
        request=httpx.Request("GET", "https://zuse.example.com/videos/1"),
    )


@override_settings(ZUSE_API_TOKEN="test-token", ZUSE_API_URL="https://zuse.example.com")
class ZuseAPIClientInitTests(TestCase):
    def test_init_sets_up_client_from_settings(self):
        client = ZuseAPIClient()

        self.assertEqual(client.token, "test-token")
        self.assertEqual(client.base_url, "https://zuse.example.com")
        self.assertEqual(client.client.headers["authorization"], "Bearer test-token")


@override_settings(ZUSE_API_TOKEN="test-token", ZUSE_API_URL="https://zuse.example.com")
class ZuseAPIClientGetVideoTests(TestCase):
    def setUp(self):
        self.client = ZuseAPIClient()

    def test_get_video_returns_parsed_json(self):
        payload = make_zuse_result(1)
        with patch.object(
            self.client.client, "get", return_value=make_response(payload)
        ) as mock_get:
            result = self.client._get_video(1)

        mock_get.assert_called_once_with("https://zuse.example.com/videos/1")
        self.assertEqual(result, payload)

    def test_get_video_raises_on_http_error_status(self):
        with (
            patch.object(
                self.client.client,
                "get",
                return_value=make_response({}, status_code=500),
            ),
            self.assertRaises(httpx.HTTPStatusError),
        ):
            self.client._get_video(1)

    def test_get_video_raises_on_request_error(self):
        with (
            patch.object(
                self.client.client,
                "get",
                side_effect=httpx.ConnectError("boom"),
            ),
            self.assertRaises(httpx.ConnectError),
        ):
            self.client._get_video(1)

    def test_get_video_raises_on_invalid_json_body(self):
        response = httpx.Response(
            200,
            content=b"not json",
            request=httpx.Request("GET", "https://zuse.example.com/videos/1"),
        )
        with (
            patch.object(self.client.client, "get", return_value=response),
            self.assertRaises(ValueError),
        ):
            self.client._get_video(1)


@override_settings(ZUSE_API_TOKEN="test-token", ZUSE_API_URL="https://zuse.example.com")
class ZuseAPIClientSyncVideosTests(TestCase):
    def setUp(self):
        self.client = ZuseAPIClient()
        self.videos = [
            TikTokVideo.objects.create(id_tiktok=100 + i, added_by=DataOrigins.DONATION)
            for i in range(3)
        ]

    def test_sync_videos_creates_classifications_for_all_videos(self):
        with patch.object(
            self.client,
            "_get_video",
            side_effect=[make_zuse_result(v.id_tiktok) for v in self.videos],
        ):
            self.client.sync_videos([v.id_tiktok for v in self.videos])

        self.assertEqual(TikTokVideoClassification.objects.count(), 3)

    def test_sync_videos_processes_in_batches(self):
        with (
            patch.object(self.client, "BATCH_SIZE", 2),
            patch.object(
                self.client,
                "_get_video",
                side_effect=[make_zuse_result(v.id_tiktok) for v in self.videos],
            ),
            patch.object(
                self.client, "_process_results", wraps=self.client._process_results
            ) as mock_process,
        ):
            self.client.sync_videos([v.id_tiktok for v in self.videos])

        # 3 videos with batch size 2 -> one batch of 2, one batch of 1
        self.assertEqual(mock_process.call_count, 2)
        self.assertEqual(len(mock_process.call_args_list[0].args[0]), 2)
        self.assertEqual(len(mock_process.call_args_list[1].args[0]), 1)

    def test_sync_videos_skips_video_on_http_status_error(self):
        error = httpx.HTTPStatusError(
            "error",
            request=httpx.Request("GET", "https://zuse.example.com/videos/1"),
            response=make_response({}, status_code=404),
        )
        with patch.object(
            self.client,
            "_get_video",
            side_effect=[error, make_zuse_result(self.videos[1].id_tiktok)],
        ):
            self.client.sync_videos(
                [self.videos[0].id_tiktok, self.videos[1].id_tiktok]
            )

        self.assertEqual(TikTokVideoClassification.objects.count(), 1)
        self.assertEqual(
            TikTokVideoClassification.objects.get().video_id, self.videos[1].pk
        )

    def test_sync_videos_skips_video_on_request_error(self):
        error = httpx.ConnectError(
            "boom", request=httpx.Request("GET", "https://zuse.example.com/videos/1")
        )
        with patch.object(
            self.client,
            "_get_video",
            side_effect=[error, make_zuse_result(self.videos[1].id_tiktok)],
        ):
            self.client.sync_videos(
                [self.videos[0].id_tiktok, self.videos[1].id_tiktok]
            )

        self.assertEqual(TikTokVideoClassification.objects.count(), 1)

    def test_sync_videos_skips_video_on_invalid_json_response(self):
        with patch.object(
            self.client,
            "_get_video",
            side_effect=[
                ValueError("Expecting value: line 1 column 1 (char 0)"),
                make_zuse_result(self.videos[1].id_tiktok),
            ],
        ):
            self.client.sync_videos(
                [self.videos[0].id_tiktok, self.videos[1].id_tiktok]
            )

        self.assertEqual(TikTokVideoClassification.objects.count(), 1)

    def test_sync_videos_skips_video_on_unexpected_payload_type(self):
        with patch.object(
            self.client,
            "_get_video",
            side_effect=[
                ["unexpected", "list"],
                make_zuse_result(self.videos[1].id_tiktok),
            ],
        ):
            self.client.sync_videos(
                [self.videos[0].id_tiktok, self.videos[1].id_tiktok]
            )

        self.assertEqual(TikTokVideoClassification.objects.count(), 1)

    def test_sync_videos_does_nothing_for_empty_input(self):
        with patch.object(self.client, "_get_video") as mock_get_video:
            self.client.sync_videos([])

        mock_get_video.assert_not_called()
        self.assertEqual(TikTokVideoClassification.objects.count(), 0)


@override_settings(ZUSE_API_TOKEN="test-token", ZUSE_API_URL="https://zuse.example.com")
class ZuseAPIClientProcessResultsTests(TestCase):
    def setUp(self):
        self.client = ZuseAPIClient()
        self.video = TikTokVideo.objects.create(
            id_tiktok=1, added_by=DataOrigins.DONATION
        )

    def test_creates_classification_with_expected_fields(self):
        result = make_zuse_result(self.video.id_tiktok)

        self.client._process_results([result])

        classification = TikTokVideoClassification.objects.get()
        self.assertEqual(classification.video_id, self.video.pk)
        self.assertTrue(classification.is_political)
        self.assertFalse(classification.political_other)
        self.assertTrue(classification.political_content)
        self.assertEqual(classification.stage1_rationale, "mentions an election")
        self.assertEqual(classification.entities, ["Senator Smith"])
        self.assertEqual(classification.keyword_matches, ["election"])
        self.assertEqual(classification.language, "en")
        self.assertEqual(classification.plausible_party, "PartyX")
        self.assertEqual(
            classification.classification_ts, datetime(2026, 9, 9, tzinfo=UTC)
        )
        self.assertEqual(classification.scraped_data, {"raw": "data"})
        self.assertEqual(
            classification.media, {"thumbnail": "https://zuse.example.com/thumb/1.jpg"}
        )
        self.assertEqual(classification.prediction_scraped, {"is_political": False})

    def test_computes_sentiment_flags_from_entities(self):
        result = make_zuse_result(
            self.video.id_tiktok,
            entities=[
                {"sentiment": "positive"},
                {"sentiment": "negative"},
                {"sentiment": None},
            ],
        )

        self.client._process_results([result])

        classification = TikTokVideoClassification.objects.get()
        self.assertTrue(classification.is_sentiment_positive)
        self.assertTrue(classification.is_sentiment_negative)
        self.assertFalse(classification.is_sentiment_neutral)

    def test_missing_predictions_div_defaults_to_none(self):
        result = make_zuse_result(self.video.id_tiktok)
        del result["predictions_div"]

        self.client._process_results([result])

        classification = TikTokVideoClassification.objects.get()
        self.assertIsNone(classification.prediction_scraped)

    def test_upserts_existing_classification_for_same_video(self):
        TikTokVideoClassification.objects.create(
            video=self.video,
            is_political=False,
            political_content=False,
            stage1_rationale="old",
        )

        result = make_zuse_result(
            self.video.id_tiktok,
            predictions={
                "is_political": True,
                "political_other": False,
                "political_content": True,
                "stage1_rationale": "new",
                "entities": [],
                "keyword_matches": [],
                "language": "en",
                "plausible_party": "PartyX",
                "created_at": datetime(2026, 9, 9, tzinfo=UTC).isoformat(),
            },
        )
        self.client._process_results([result])

        self.assertEqual(TikTokVideoClassification.objects.count(), 1)
        classification = TikTokVideoClassification.objects.get()
        self.assertTrue(classification.is_political)
        self.assertTrue(classification.political_content)
        self.assertEqual(classification.stage1_rationale, "new")

    def test_skips_result_missing_required_field(self):
        result = make_zuse_result(self.video.id_tiktok)
        del result["predictions"]["stage1_rationale"]

        with self.assertLogs("ddcs.metadata.services", level="WARNING"):
            self.client._process_results([result])

        self.assertEqual(TikTokVideoClassification.objects.count(), 0)

    def test_skips_result_with_malformed_video_id(self):
        result = make_zuse_result("not-an-int")

        with self.assertLogs("ddcs.metadata.services", level="WARNING"):
            self.client._process_results([result])

        self.assertEqual(TikTokVideoClassification.objects.count(), 0)

    def test_skips_result_for_unknown_id_tiktok(self):
        result = make_zuse_result(999999)

        with self.assertLogs("ddcs.metadata.services", level="WARNING"):
            self.client._process_results([result])

        self.assertEqual(TikTokVideoClassification.objects.count(), 0)

    def test_one_malformed_result_does_not_block_valid_ones(self):
        other_video = TikTokVideo.objects.create(
            id_tiktok=2, added_by=DataOrigins.DONATION
        )
        bad_result = make_zuse_result(self.video.id_tiktok)
        del bad_result["predictions"]
        good_result = make_zuse_result(other_video.id_tiktok)

        with self.assertLogs("ddcs.metadata.services", level="WARNING"):
            self.client._process_results([bad_result, good_result])

        self.assertEqual(TikTokVideoClassification.objects.count(), 1)
        self.assertEqual(
            TikTokVideoClassification.objects.get().video_id, other_video.pk
        )

    def test_empty_results_does_not_touch_db(self):
        with patch(
            "ddcs.metadata.services.TikTokVideoClassification.objects.bulk_create"
        ) as mock_bulk_create:
            self.client._process_results([])

        mock_bulk_create.assert_not_called()
