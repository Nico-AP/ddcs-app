import csv
import os
import unittest
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from ddm.participation.models import Participant
from django.http import Http404
from django.test import RequestFactory, TestCase

from ddcs.core.types import TikTokUserData
from ddcs.metadata.models import DataOrigins, TikTokHashtag, TikTokUser, TikTokVideo
from ddcs.reports import factories, plots, services, views, wordclouds
from ddcs.reports.behaviour_metrics import (
    compute_behaviour_comparisons,
    compute_watch_history_metrics,
)
from ddcs.reports.config import (
    ACCOUNT_PARTY_MAPPING_CSV_PATH,
    HASHTAGS_TO_EXCLUDE,
    NO_PARTY_KEY,
    REPORT_FIRST_DATE_TO_INCLUDE,
)
from ddcs.reports.factories import get_synthetic_report_statistics
from ddcs.reports.utils import load_account_party_mapping

# ============================================================
# utils
# ============================================================


class LoadAccountPartyMappingTests(TestCase):
    def test_returns_dict(self):
        self.assertIsInstance(load_account_party_mapping(), dict)

    def test_csv_has_required_columns(self):
        # Loader reads `username` and `partei`; the CSV must provide both.
        expected_columns = {"username", "partei"}
        with Path(ACCOUNT_PARTY_MAPPING_CSV_PATH).open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            self.assertEqual(set(reader.fieldnames), expected_columns)

    def test_maps_username_to_party(self):
        result = load_account_party_mapping()
        # Spot-check that values are non-empty party strings.
        self.assertTrue(all(isinstance(k, str) and k for k in result))
        self.assertTrue(all(isinstance(v, str) and v for v in result.values()))


# ============================================================
# behaviour_metrics
# ============================================================


class FracInstantSkipTests(TestCase):
    def _watch_history(self, offsets_sec: list[float]) -> TikTokUserData:
        base = REPORT_FIRST_DATE_TO_INCLUDE
        return TikTokUserData(
            watch_history=[
                {
                    "date": base + timedelta(seconds=offset),
                    "link": f"https://www.tiktok.com/@user/video/{i}",
                    "video_id": i,
                }
                for i, offset in enumerate(offsets_sec)
            ]
        )

    def test_empty_history_returns_no_metrics(self):
        self.assertEqual(compute_watch_history_metrics(TikTokUserData()), {})

    def test_single_watch_has_zero_instant_skip_fraction(self):
        metrics = compute_watch_history_metrics(self._watch_history([0]))
        self.assertEqual(metrics["frac_instant_skip"], 0.0)

    def test_counts_gaps_shorter_than_one_second(self):
        metrics = compute_watch_history_metrics(self._watch_history([0, 0.5, 10]))
        self.assertEqual(metrics["frac_instant_skip"], 0.5)

    @unittest.skipIf(
        os.getenv("GITHUB_ACTIONS") == "true",
        "Skipping integration test in CI environment",
    )
    def test_included_in_behaviour_comparisons_when_reference_csv_present(self):
        # CSV is not present in gh actions
        comparisons = compute_behaviour_comparisons(self._watch_history([0, 0.5, 10]))
        metrics = {row["metric"] for row in comparisons}
        self.assertIn("frac_instant_skip", metrics)


# ============================================================
# services — pure helpers
# ============================================================


class GetVideoIdListTests(TestCase):
    def test_returns_empty_for_none(self):
        self.assertEqual(services._get_video_id_list(None), [])

    def test_returns_empty_for_empty_list(self):
        self.assertEqual(services._get_video_id_list([]), [])

    def test_filters_records_before_cutoff(self):
        after = REPORT_FIRST_DATE_TO_INCLUDE + timedelta(days=1)
        before = REPORT_FIRST_DATE_TO_INCLUDE - timedelta(days=1)
        data = [
            {"date": after, "video_id": 1},
            {"date": before, "video_id": 2},
        ]
        self.assertEqual(services._get_video_id_list(data), [1])

    def test_includes_records_on_cutoff(self):
        data = [{"date": REPORT_FIRST_DATE_TO_INCLUDE, "video_id": 9}]
        self.assertEqual(services._get_video_id_list(data), [9])

    def test_skips_records_with_unparseable_date(self):
        data = [
            {"date": "not a date", "video_id": 1},
            {"date": REPORT_FIRST_DATE_TO_INCLUDE, "video_id": 2},
        ]
        self.assertEqual(services._get_video_id_list(data), [2])

    def test_skips_records_with_missing_video_id(self):
        data = [
            {"date": REPORT_FIRST_DATE_TO_INCLUDE, "video_id": None},
            {"date": REPORT_FIRST_DATE_TO_INCLUDE},
            {"date": REPORT_FIRST_DATE_TO_INCLUDE, "video_id": 5},
        ]
        self.assertEqual(services._get_video_id_list(data), [5])

    def test_preserves_duplicates_and_order(self):
        d = REPORT_FIRST_DATE_TO_INCLUDE + timedelta(hours=1)
        data = [
            {"date": d, "video_id": 1},
            {"date": d, "video_id": 2},
            {"date": d, "video_id": 1},
        ]
        self.assertEqual(services._get_video_id_list(data), [1, 2, 1])


class GetUsernameListTests(TestCase):
    def test_returns_empty_for_none(self):
        self.assertEqual(services._get_username_list(None), [])

    def test_returns_empty_for_empty_list(self):
        self.assertEqual(services._get_username_list([]), [])

    def test_extracts_usernames(self):
        data = [{"username": "alice"}, {"username": "bob"}]
        self.assertEqual(services._get_username_list(data), ["alice", "bob"])

    def test_skips_records_without_username(self):
        data = [{"username": None}, {"username": "alice"}, {}]
        self.assertEqual(services._get_username_list(data), ["alice"])


class BuildPoliticalVideoMetadataTests(TestCase):
    def _video(self, id_tiktok: int, name: str | None) -> MagicMock:
        m = MagicMock()
        m.id_tiktok = id_tiktok
        if name is None:
            m.user = None
        else:
            m.user.name = name
        return m

    def test_party_account_videos_map_to_csv_party(self):
        videos = [self._video(1, "alice"), self._video(2, "bob")]
        mapping = {"alice": "SPD", "bob": "CDU/CSU"}
        party_map, username_map = services._build_political_video_metadata(
            videos, [], mapping
        )
        self.assertEqual(party_map, {1: "SPD", 2: "CDU/CSU"})
        self.assertEqual(username_map, {1: "alice", 2: "bob"})

    def test_party_account_video_with_unmapped_user_is_skipped(self):
        videos = [self._video(1, "alice"), self._video(2, "stranger")]
        mapping = {"alice": "SPD"}
        party_map, username_map = services._build_political_video_metadata(
            videos, [], mapping
        )
        self.assertEqual(party_map, {1: "SPD"})
        self.assertEqual(username_map, {1: "alice"})

    def test_non_party_political_videos_map_to_no_party_key(self):
        non_party = [self._video(10, "stranger"), self._video(11, "outsider")]
        party_map, username_map = services._build_political_video_metadata(
            [], non_party, {}
        )
        self.assertEqual(party_map, {10: NO_PARTY_KEY, 11: NO_PARTY_KEY})
        self.assertEqual(username_map, {10: "stranger", 11: "outsider"})

    def test_non_party_video_without_user_gets_empty_username(self):
        party_map, username_map = services._build_political_video_metadata(
            [], [self._video(99, None)], {}
        )
        self.assertEqual(party_map, {99: NO_PARTY_KEY})
        self.assertEqual(username_map, {99: ""})

    def test_combines_both_buckets(self):
        party_videos = [self._video(1, "alice")]
        non_party = [self._video(2, "stranger")]
        party_map, username_map = services._build_political_video_metadata(
            party_videos, non_party, {"alice": "SPD"}
        )
        self.assertEqual(party_map, {1: "SPD", 2: NO_PARTY_KEY})
        self.assertEqual(username_map, {1: "alice", 2: "stranger"})

    def test_returns_empty_maps_for_no_videos(self):
        party_map, username_map = services._build_political_video_metadata([], [], {})
        self.assertEqual(party_map, {})
        self.assertEqual(username_map, {})


class ComputePartyCountsTests(TestCase):
    def test_counts_per_party_and_bucket_unknown(self):
        result = services._compute_party_counts(
            seen_video_ids=[1, 1, 2, 99],
            video_party_map={1: "SPD", 2: "CDU/CSU"},
        )
        as_dict = {r["party"]: r["count"] for r in result}
        self.assertEqual(as_dict, {"SPD": 2, "CDU/CSU": 1, NO_PARTY_KEY: 1})

    def test_returns_empty_list_for_no_videos(self):
        self.assertEqual(services._compute_party_counts([], {}), [])

    def test_all_buckets_to_no_party_when_no_political_videos_seen(self):
        result = services._compute_party_counts([10, 20], {})
        self.assertEqual(result, [{"party": NO_PARTY_KEY, "count": 2}])

    def test_orders_by_parties_order_constant(self):
        # Input order intentionally reversed vs PARTIES_ORDER.
        result = services._compute_party_counts(
            seen_video_ids=[1, 2, 3, 4, 99],
            video_party_map={1: "AfD", 2: "SPD", 3: "CDU/CSU", 4: "Grüne"},
        )
        self.assertEqual(
            [r["party"] for r in result],
            ["SPD", "CDU/CSU", "Grüne", "AfD", NO_PARTY_KEY],
        )

    def test_unknown_party_sorts_after_known_alphabetically(self):
        result = services._compute_party_counts(
            seen_video_ids=[1, 2, 3],
            video_party_map={1: "SPD", 2: "Volt", 3: "Tierschutz"},
        )
        parties = [r["party"] for r in result]
        self.assertEqual(parties[0], "SPD")
        self.assertEqual(parties[1:], ["Tierschutz", "Volt"])


class ComputeDailyPartyCountsTests(TestCase):
    def _record(self, day: str, video_id: int):
        dt = datetime.fromisoformat(day).replace(tzinfo=UTC)
        return {"date": dt, "video_id": video_id}

    def test_groups_by_day_and_party(self):
        records = [
            self._record("2026-05-08", 1),
            self._record("2026-05-08", 1),
            self._record("2026-05-09", 2),
        ]
        video_party_map = {1: "SPD", 2: "CDU/CSU"}
        result = services._compute_daily_party_counts(records, video_party_map)
        self.assertIn({"date": "2026-05-08", "party": "SPD", "count": 2}, result)
        self.assertIn({"date": "2026-05-09", "party": "CDU/CSU", "count": 1}, result)

    def test_sorted_by_date(self):
        records = [
            self._record("2026-06-01", 2),
            self._record("2026-05-08", 1),
            self._record("2026-05-09", 1),
        ]
        result = services._compute_daily_party_counts(records, {1: "SPD", 2: "CDU/CSU"})
        dates = [r["date"] for r in result]
        self.assertEqual(dates, sorted(dates))

    def test_buckets_unmapped_to_no_party(self):
        records = [self._record("2026-05-08", 999)]
        result = services._compute_daily_party_counts(records, {})
        self.assertEqual(
            result, [{"date": "2026-05-08", "party": NO_PARTY_KEY, "count": 1}]
        )

    def test_skips_records_with_invalid_date_or_missing_video_id(self):
        records = [
            {"date": "not a date", "video_id": 1},
            {"date": datetime(2026, 5, 8, tzinfo=UTC), "video_id": None},
            self._record("2026-05-08", 1),
        ]
        result = services._compute_daily_party_counts(records, {1: "SPD"})
        self.assertEqual(result, [{"date": "2026-05-08", "party": "SPD", "count": 1}])


class GetTopVideosTests(TestCase):
    def test_returns_videos_sorted_by_view_count_desc(self):
        seen = [1, 2, 2, 3, 3, 3]
        result = services._get_top_videos(
            seen_pol_video_ids=seen,
            video_party_map={1: "SPD", 2: "CDU/CSU", 3: "Grüne"},
            username_by_video={1: "alice", 2: "bob", 3: "carol"},
            hashtags_by_video={1: ["a"], 2: ["b"], 3: ["c"]},
            n=3,
        )
        self.assertEqual([v["video_id"] for v in result], [3, 2, 1])
        self.assertEqual(result[0]["view_count"], 3)
        self.assertEqual(result[0]["party"], "Grüne")
        self.assertEqual(result[0]["username"], "carol")
        self.assertEqual(result[0]["hashtags"], ["c"])

    def test_respects_n_limit(self):
        seen = [1, 2, 3, 4, 5, 6, 7]
        result = services._get_top_videos(seen, {}, {}, {}, n=2)
        self.assertEqual(len(result), 2)

    def test_returns_empty_for_no_seen_videos(self):
        self.assertEqual(services._get_top_videos([], {}, {}, {}), [])

    def test_hashtags_default_to_empty_list_when_missing(self):
        result = services._get_top_videos([1], {1: "SPD"}, {1: "alice"}, {}, n=1)
        self.assertEqual(result[0]["hashtags"], [])

    def test_username_defaults_to_empty_string_when_missing(self):
        result = services._get_top_videos([1], {1: "SPD"}, {}, {}, n=1)
        self.assertEqual(result[0]["username"], "")


# ============================================================
# services — DB-touching helpers
# ============================================================


class GetHashtagsByVideoTests(TestCase):
    def setUp(self):
        self.tag_a = TikTokHashtag.objects.create(
            name="a", added_by=DataOrigins.DONATION
        )
        self.tag_b = TikTokHashtag.objects.create(
            name="b", added_by=DataOrigins.DONATION
        )
        self.video = TikTokVideo.objects.create(
            id_tiktok=111, added_by=DataOrigins.DONATION
        )
        self.video.hashtags.set([self.tag_a, self.tag_b])
        self.other_video = TikTokVideo.objects.create(
            id_tiktok=222, added_by=DataOrigins.DONATION
        )

    def test_returns_hashtags_for_matched_videos(self):
        result = services._get_hashtags_by_video([111, 222])
        self.assertEqual(sorted(result[111]), ["a", "b"])
        self.assertEqual(result[222], [])

    def test_returns_empty_dict_for_no_ids(self):
        self.assertEqual(services._get_hashtags_by_video([]), {})

    def test_ignores_unknown_video_ids(self):
        result = services._get_hashtags_by_video([999])
        self.assertEqual(result, {})


# ============================================================
# services — orchestration (DB integration)
# ============================================================


class ComputeReportStatisticsTests(TestCase):
    """End-to-end DB integration tests for compute_report_statistics.

    Covers the dual definition of "political video":
    party-account videos (CSV) + videos with a monitored hashtag.
    """

    def setUp(self):
        self.party_user = TikTokUser.objects.create(
            name="alice", added_by=DataOrigins.DONATION
        )
        self.stranger = TikTokUser.objects.create(
            name="stranger", added_by=DataOrigins.DONATION
        )
        self.tag_pol = TikTokHashtag.objects.create(
            name="politik", added_by=DataOrigins.DONATION, monitor_api=True
        )
        self.tag_other = TikTokHashtag.objects.create(
            name="cooking", added_by=DataOrigins.DONATION, monitor_api=False
        )
        # v1: party account
        self.v_party = TikTokVideo.objects.create(
            id_tiktok=1, user=self.party_user, added_by=DataOrigins.DONATION
        )
        # v2: non-party user posting with monitored hashtag → non-party political
        self.v_nonparty = TikTokVideo.objects.create(
            id_tiktok=2, user=self.stranger, added_by=DataOrigins.DONATION
        )
        self.v_nonparty.hashtags.add(self.tag_pol)
        # v3: non-party user, non-monitored hashtag → not political
        self.v_neutral = TikTokVideo.objects.create(
            id_tiktok=3, user=self.stranger, added_by=DataOrigins.DONATION
        )
        self.v_neutral.hashtags.add(self.tag_other)
        # v4: party account that also uses a monitored hashtag — must end up
        # in the party set, not double-counted in the non-party set.
        self.v_party_pol = TikTokVideo.objects.create(
            id_tiktok=4, user=self.party_user, added_by=DataOrigins.DONATION
        )
        self.v_party_pol.hashtags.add(self.tag_pol)

    def _patch_csv(self, mapping: dict[str, str] | None = None):
        return patch.object(
            services,
            "load_account_party_mapping",
            return_value=mapping if mapping is not None else {"alice": "SPD"},
        )

    def test_full_pipeline_classifies_party_and_non_party_videos(self):
        cutoff = REPORT_FIRST_DATE_TO_INCLUDE + timedelta(days=1)
        data = TikTokUserData(
            watch_history=[
                {"date": cutoff, "video_id": 1},
                {"date": cutoff, "video_id": 2},
                {"date": cutoff, "video_id": 3},
                {"date": cutoff, "video_id": 4},
            ],
            followed_accounts=[{"username": "alice"}, {"username": "stranger"}],
            liked_videos=[{"date": cutoff, "video_id": 2}],
        )
        with self._patch_csv():
            result = services.compute_report_statistics(data)

        # v1, v2 and v4 are political; v3 is not.
        self.assertEqual(set(result["seen_pol_video_ids"]), {1, 2, 4})
        self.assertEqual(result["liked_pol_video_ids"], [2])
        # stranger isn't in the CSV, so it doesn't appear in followed_pol_users.
        self.assertEqual(result["followed_pol_users"], ["alice"])
        # Non-party political video's hashtags go to the non-party bucket;
        # party-account videos' hashtags go to the party bucket.
        self.assertEqual(result["non_party_hashtags"], ["politik"])
        self.assertEqual(result["party_hashtags"], ["politik"])
        # Total watched includes the neutral video too.
        self.assertEqual(result["videos_seen_count_total"], 4)

    def test_party_account_with_monitored_hashtag_is_not_double_counted(self):
        cutoff = REPORT_FIRST_DATE_TO_INCLUDE + timedelta(days=1)
        data = TikTokUserData(
            watch_history=[{"date": cutoff, "video_id": 4}],
        )
        with self._patch_csv():
            result = services.compute_report_statistics(data)

        # v4 (party-account + monitored hashtag) — counts once, as SPD.
        self.assertEqual(result["seen_pol_video_ids"], [4])
        as_dict = {r["party"]: r["count"] for r in result["party_counts"]}
        self.assertEqual(as_dict, {"SPD": 1})
        # Its hashtags must NOT appear in non_party_hashtags.
        self.assertEqual(result["non_party_hashtags"], [])

    def test_top_videos_include_non_party_username(self):
        cutoff = REPORT_FIRST_DATE_TO_INCLUDE + timedelta(days=1)
        data = TikTokUserData(
            watch_history=[
                {"date": cutoff, "video_id": 2},
                {"date": cutoff, "video_id": 2},
                {"date": cutoff, "video_id": 1},
            ],
        )
        with self._patch_csv():
            result = services.compute_report_statistics(data)

        by_id = {v["video_id"]: v for v in result["top_videos"]}
        self.assertEqual(by_id[2]["username"], "stranger")
        self.assertEqual(by_id[2]["party"], NO_PARTY_KEY)
        self.assertEqual(by_id[1]["username"], "alice")
        self.assertEqual(by_id[1]["party"], "SPD")

    def test_handles_completely_empty_user_data(self):
        with self._patch_csv():
            result = services.compute_report_statistics(TikTokUserData())
        self.assertEqual(result["videos_seen_count_total"], 0)
        self.assertEqual(result["seen_pol_video_ids"], [])
        self.assertEqual(result["liked_pol_video_ids"], [])
        self.assertEqual(result["followed_pol_users"], [])
        self.assertEqual(result["party_counts"], [])
        self.assertEqual(result["daily_party_counts"], [])


class GenerateReportStatisticsTests(TestCase):
    @patch.object(services, "compute_report_statistics")
    def test_persists_statistics_to_db(self, mock_compute):
        mock_compute.return_value = {
            "videos_seen_count_total": 5,
            "seen_pol_video_ids": [1, 2],
            "liked_pol_video_ids": [],
            "followed_pol_users": [],
            "party_counts": [],
            "daily_party_counts": [],
            "hashtags_by_pol_video": {},
            "top_videos": [],
            "party_hashtags": [],
            "non_party_hashtags": [],
        }
        participant = MagicMock()
        # ParticipantReportStatistics.objects.create needs a real Participant FK;
        # patch the model.create call directly to keep this a pure unit test.
        with patch.object(
            services.ParticipantReportStatistics.objects, "create"
        ) as mock_create:
            mock_create.return_value = MagicMock()
            result = services.generate_report_statistics(participant, TikTokUserData())

        mock_compute.assert_called_once()
        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        self.assertEqual(kwargs["participant"], participant)
        self.assertEqual(kwargs["videos_seen_count_total"], 5)
        self.assertEqual(kwargs["seen_pol_video_ids"], [1, 2])
        self.assertIs(result, mock_create.return_value)


# ============================================================
# factories
# ============================================================


class SyntheticFactoriesTests(TestCase):
    def test_party_counts_covers_all_known_parties(self):
        result = factories._synthetic_party_counts()
        parties = {r["party"] for r in result}
        self.assertEqual(parties, set(factories.SYNTHETIC_PARTIES))
        self.assertTrue(all(r["count"] >= 1 for r in result))

    def test_daily_party_counts_has_one_record_per_day_and_party(self):
        days = 7
        result = factories._synthetic_daily_party_counts(days=days)
        self.assertEqual(len(result), days * len(factories.SYNTHETIC_PARTIES))
        unique_dates = {r["date"] for r in result}
        self.assertEqual(len(unique_dates), days)

    def test_top_videos_dedupes_and_respects_limit(self):
        ids = [1, 1, 2, 3, 4, 5, 6, 7]
        result = factories._synthetic_top_videos(ids, n=3)
        self.assertLessEqual(len(result), 3)
        self.assertEqual(len({r["video_id"] for r in result}), len(result))

    def test_top_videos_returns_empty_for_no_ids(self):
        self.assertEqual(factories._synthetic_top_videos([]), [])

    def test_hashtags_by_video_returns_one_entry_per_id(self):
        result = factories._synthetic_hashtags_by_video([1, 2, 3])
        self.assertEqual(set(result), {1, 2, 3})

    def test_get_synthetic_report_statistics_builds_unsaved_instance(self):
        # Bypass the unsaved Participant instance assignment to the FK by
        # constructing the model after the factory builds its kwargs.
        captured = {}

        original_init = factories.ParticipantReportStatistics.__init__

        def capture_init(self, *args, **kwargs):
            captured.update(kwargs)
            # Avoid hitting the FK descriptor for a fake participant.
            kwargs.pop("participant", None)
            original_init(self, *args, **kwargs)

        with patch.object(
            factories.ParticipantReportStatistics, "__init__", capture_init
        ):
            result = get_synthetic_report_statistics(Participant())

        self.assertIsNone(result.pk)
        self.assertGreater(len(captured["seen_pol_video_ids"]), 0)
        self.assertGreater(len(captured["party_counts"]), 0)
        self.assertGreater(len(captured["party_hashtags"]), 0)


# ============================================================
# plots
# ============================================================


class PartyDistributionPlotTests(TestCase):
    def test_returns_none_html_when_only_no_party_data(self):
        result = plots.get_party_distribution_plot_user(
            [{"party": NO_PARTY_KEY, "count": 5}]
        )
        self.assertEqual(result, {"html": None})

    def test_returns_none_html_when_empty(self):
        self.assertEqual(plots.get_party_distribution_plot_user([]), {"html": None})

    def test_returns_html_when_party_data_present(self):
        result = plots.get_party_distribution_plot_user(
            [{"party": "SPD", "count": 5}, {"party": "CDU/CSU", "count": 3}]
        )
        self.assertIsNotNone(result["html"])
        self.assertIn("plotly", result["html"].lower())


class TemporalPartyDistributionPlotTests(TestCase):
    def test_returns_none_html_when_empty(self):
        self.assertEqual(
            plots.get_temporal_party_distribution_plot_user([]), {"html": None}
        )

    def test_returns_none_html_when_only_no_party_records(self):
        result = plots.get_temporal_party_distribution_plot_user(
            [{"date": "2026-05-08", "party": NO_PARTY_KEY, "count": 1}]
        )
        self.assertEqual(result, {"html": None})

    def test_returns_html_when_party_records_present(self):
        result = plots.get_temporal_party_distribution_plot_user(
            [
                {"date": "2026-05-08", "party": "SPD", "count": 2},
                {"date": "2026-05-09", "party": "SPD", "count": 1},
            ]
        )
        self.assertIsNotNone(result["html"])


class HexToRgbaTests(TestCase):
    def test_converts_with_default_alpha(self):
        self.assertEqual(plots._hex_to_rgba("#ff8000"), "rgba(255, 128, 0, 0.9)")

    def test_accepts_hex_without_hash(self):
        self.assertEqual(plots._hex_to_rgba("000000", alpha=0.5), "rgba(0, 0, 0, 0.5)")


# ============================================================
# wordclouds
# ============================================================


class RemoveEmojisTests(TestCase):
    def test_lowercases_ascii(self):
        self.assertEqual(wordclouds._remove_emojis("Hello"), "hello")

    def test_strips_emoji(self):
        self.assertEqual(wordclouds._remove_emojis("politik🇩🇪"), "politik")

    def test_preserves_german_umlauts(self):
        self.assertEqual(wordclouds._remove_emojis("überraschung"), "überraschung")
        self.assertEqual(wordclouds._remove_emojis("WählEN"), "wählen")

    def test_strips_symbols_and_punctuation(self):
        self.assertEqual(wordclouds._remove_emojis("a-b_c.d"), "abcd")


class BuildHashtagFrequenciesTests(TestCase):
    def test_counts_frequencies(self):
        result = wordclouds._build_hashtag_frequencies(["politik", "Politik", "wahl"])
        self.assertEqual(result["politik"], 2)
        self.assertEqual(result["wahl"], 1)

    def test_excludes_blocked_hashtags(self):
        blocked = next(iter(HASHTAGS_TO_EXCLUDE))
        result = wordclouds._build_hashtag_frequencies(["politik", blocked])
        self.assertNotIn(blocked, result)
        self.assertIn("politik", result)

    def test_drops_emoji_only_hashtag(self):
        result = wordclouds._build_hashtag_frequencies(["🇩🇪", "politik"])
        self.assertEqual(set(result), {"politik"})


class CreateWordcloudTests(TestCase):
    def test_returns_none_html_for_empty_frequencies(self):
        self.assertEqual(
            wordclouds._create_wordcloud(Counter(), (255, 0, 0)), {"html": None}
        )

    def test_returns_svg_html_for_non_empty_frequencies(self):
        result = wordclouds._create_wordcloud(
            Counter({"politik": 5, "wahl": 3}), (255, 0, 0)
        )
        self.assertIsNotNone(result["html"])
        self.assertIn("wordcloud-container", result["html"])
        self.assertIn("<svg", result["html"])


class GetWordcloudTests(TestCase):
    """Smoke tests for the unified public wordcloud entry point."""

    def test_party_account_returns_html(self):
        result = wordclouds.get_wordcloud(["politik", "wahl"], is_party_account=True)
        self.assertIsNotNone(result["html"])

    def test_noparty_account_returns_html(self):
        result = wordclouds.get_wordcloud(["politik", "wahl"], is_party_account=False)
        self.assertIsNotNone(result["html"])

    def test_returns_none_html_for_empty_input(self):
        self.assertEqual(
            wordclouds.get_wordcloud([], is_party_account=True), {"html": None}
        )


# ============================================================
# views
# ============================================================


class FilterHashtagsTests(TestCase):
    def test_excludes_blocked_hashtags_case_insensitive(self):
        result = views._filter_hashtags(["FYP", "politik", "Trending"])
        self.assertEqual(result, ["politik"])

    def test_does_not_impose_length_limit(self):
        tags = [f"tag{i}" for i in range(20)]
        self.assertEqual(len(views._filter_hashtags(tags)), 20)

    def test_handles_empty_list(self):
        self.assertEqual(views._filter_hashtags([]), [])


class MainReportViewTests(TestCase):
    def test_puts_participant_id_in_context(self):
        request = RequestFactory().get("/report/abc/")
        response = views.MainReportView.as_view()(request, participant_id="abc123")
        self.assertEqual(response.context_data["participant_id"], "abc123")


class GetReportViewTests(TestCase):
    def _statistics(self, **overrides) -> MagicMock:
        defaults = {
            "videos_seen_count_total": 100,
            "seen_pol_video_ids": [1, 2, 3],
            "party_counts": [{"party": "SPD", "count": 3}],
            "daily_party_counts": [{"date": "2026-05-08", "party": "SPD", "count": 3}],
            "top_videos": [
                {
                    "video_id": 1,
                    "view_count": 5,
                    "party": "SPD",
                    "hashtags": ["politik"],
                },
            ],
            "party_hashtags": ["politik"],
            "non_party_hashtags": ["news"],
            "behaviour_comparisons": [],
        }

        defaults.update(overrides)
        stats = MagicMock(spec_set=list(defaults))
        for key, value in defaults.items():
            setattr(stats, key, value)
        return stats

    def test_setup_raises_404_when_participant_missing(self):
        request = RequestFactory().get("/report/get/missing/")
        view = views.GetReportView()
        with self.assertRaises(Http404):
            view.setup(request, participant_id="missing")

    def test_context_includes_intro_text_fields(self):
        view = views.GetReportView()
        view.statistics = self._statistics()
        view.kwargs = {}
        with (
            patch.object(
                views, "get_party_distribution_plot_user", return_value={"html": "p"}
            ),
            patch.object(
                views,
                "get_temporal_party_distribution_plot_user",
                return_value={"html": "t"},
            ),
            patch.object(views, "get_wordcloud") as mock_get_wordcloud,
        ):
            mock_get_wordcloud.side_effect = lambda hashtags, is_party_account: {
                "html": "party" if is_party_account else "non_party"
            }
            context = view.get_context_data()

        self.assertEqual(context["n_seen_pol_videos"], 3)
        self.assertEqual(context["n_seen_total"], 100)
        self.assertEqual(context["share_political"], 3.0)
        self.assertEqual(context["start_date"], REPORT_FIRST_DATE_TO_INCLUDE)
        self.assertEqual(context["party_distribution_user"], {"html": "p"})
        self.assertEqual(context["temporal_party_distribution_user"], {"html": "t"})
        self.assertEqual(context["wordcloud_party_user"], {"html": "party"})
        self.assertEqual(context["wordcloud_non_party_user"], {"html": "non_party"})
        mock_get_wordcloud.assert_any_call(["politik"], is_party_account=True)
        mock_get_wordcloud.assert_any_call(["news"], is_party_account=False)

    def test_share_political_is_none_when_no_videos_seen(self):
        view = views.GetReportView()
        view.statistics = self._statistics(
            videos_seen_count_total=0, seen_pol_video_ids=[]
        )
        view.kwargs = {}
        with (
            patch.object(
                views, "get_party_distribution_plot_user", return_value={"html": None}
            ),
            patch.object(
                views,
                "get_temporal_party_distribution_plot_user",
                return_value={"html": None},
            ),
            patch.object(views, "get_wordcloud", return_value={"html": None}),
        ):
            context = view.get_context_data()
        self.assertIsNone(context["share_political"])

    def test_top_videos_table_filters_blocked_hashtags(self):
        view = views.GetReportView()
        view.statistics = self._statistics(
            top_videos=[
                {
                    "video_id": 1,
                    "view_count": 10,
                    "party": "SPD",
                    "hashtags": ["fyp", "politik", "wahl"],
                },
            ],
        )
        result = view.get_top_videos_table_stats()
        self.assertEqual(result[0]["filtered_hashtags"], ["politik", "wahl"])

    def test_top_videos_table_preserves_input_order(self):
        # services already returns top_videos sorted desc by view_count;
        # the view trusts that order and does not re-sort.
        view = views.GetReportView()
        view.statistics = self._statistics(
            top_videos=[
                {"video_id": 2, "view_count": 9, "party": "SPD", "hashtags": []},
                {"video_id": 3, "view_count": 5, "party": "SPD", "hashtags": []},
                {"video_id": 1, "view_count": 2, "party": "SPD", "hashtags": []},
            ],
        )
        result = view.get_top_videos_table_stats()
        self.assertEqual([v["video_id"] for v in result], [2, 3, 1])


class GetSyntheticReportViewTests(TestCase):
    def test_setup_populates_synthetic_statistics(self):
        request = RequestFactory().get("/report/get/synthetic/")
        view = views.GetSyntheticReportView()
        view.setup(request)
        self.assertIsNotNone(view.statistics.seen_pol_video_ids)
        self.assertIsNotNone(view.statistics.party_counts)
