import csv
import os
import unittest
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from ddm.participation.models import Participant
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.http import Http404
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

import ddcs.reports.plots.utils
from ddcs.core.types import TikTokUserData
from ddcs.metadata.models import (
    DataOrigins,
    SyncAttempt,
    TikTokHashtag,
    TikTokUser,
    TikTokVideo,
)
from ddcs.metadata.research_api.models import APIVideoInfos
from ddcs.reports import factories, services, views, wordclouds
from ddcs.reports.behaviour_metrics import (
    _build_peak_hour_comparison,
    _peak_hour_same_fraction,
    apply_reference_demographic_filter,
    compute_behaviour_comparisons,
    compute_engagement_metrics,
    compute_watch_history_metrics,
    normalize_age_group,
    normalize_gender_filter,
    reference_group_size,
)
from ddcs.reports.config import (
    ACCOUNT_PARTY_MAPPING_CSV_PATH,
    HASHTAGS_TO_EXCLUDE,
    NO_PARTY_KEY,
    REPORT_FIRST_DATE_TO_INCLUDE,
)
from ddcs.reports.factories import get_synthetic_report_statistics
from ddcs.reports.metrics import account_metrics, user_metrics
from ddcs.reports.plots import public_plots, user_plots
from ddcs.reports.utils import (
    build_tiktok_embed_url,
    build_top_video_tiktok_url,
    enrich_top_videos_for_embed,
    load_account_party_mapping,
    parse_tiktok_username_from_url,
    parse_tiktok_video_id_from_url,
)
from ddcs.reports.views import PublicPlotsDevView

User = get_user_model()

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


class TopVideoUrlTests(TestCase):
    def test_parse_video_id_from_video_and_photo_urls(self):
        self.assertEqual(
            parse_tiktok_video_id_from_url(
                "https://www.tiktok.com/@alice_weidel_afd/video/7658941918302326048"
            ),
            7658941918302326048,
        )
        self.assertEqual(
            parse_tiktok_video_id_from_url(
                "https://www.tiktok.com/@die.linke/photo/7623456044794055968"
            ),
            7623456044794055968,
        )

    def test_parse_username_from_url(self):
        self.assertEqual(
            parse_tiktok_username_from_url(
                "https://www.tiktok.com/@deinespd/video/7657187761883041057"
            ),
            "deinespd",
        )

    def test_build_url_uses_username_when_available(self):
        url = build_top_video_tiktok_url(
            {"video_id": 123, "username": "deinespd", "view_count": 1}
        )
        self.assertEqual(url, "https://www.tiktok.com/@deinespd/video/123")

    def test_build_embed_url(self):
        self.assertEqual(
            build_tiktok_embed_url(7658941918302326048),
            "https://www.tiktok.com/player/v1/7658941918302326048?autoplay=0",
        )

    def test_enrich_top_videos_limits_to_three(self):
        videos = [
            {"video_id": index, "username": f"user{index}", "view_count": index}
            for index in range(5)
        ]
        enriched = enrich_top_videos_for_embed(videos)
        self.assertEqual(len(enriched), 3)
        self.assertTrue(all(video["tiktok_url"] for video in enriched))
        self.assertTrue(all(video["embed_url"] for video in enriched))


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
        comparisons = compute_behaviour_comparisons(
            self._watch_history([0, 0.5, 10]), frozenset()
        )
        metrics = {row["metric"] for row in comparisons}
        self.assertIn("frac_instant_skip", metrics)


class WatchSessionTests(TestCase):
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

    def test_single_session_duration_and_video_count(self):
        metrics = compute_watch_history_metrics(self._watch_history([0, 30, 60]))
        self.assertEqual(metrics["avg_session_length_sec"], 60.0)
        self.assertEqual(metrics["avg_videos_per_session"], 3.0)

    def test_ninety_second_break_starts_new_session(self):
        metrics = compute_watch_history_metrics(self._watch_history([0, 50, 200]))
        self.assertEqual(metrics["avg_session_length_sec"], 25.0)
        self.assertEqual(metrics["avg_videos_per_session"], 1.5)


class PoliticalEngagementTests(TestCase):
    def test_fraction_counts_likes_shares_saves_and_comments(self):
        base = REPORT_FIRST_DATE_TO_INCLUDE
        data = TikTokUserData(
            watch_history=[
                {
                    "date": base,
                    "link": "https://www.tiktok.com/@user/video/1",
                    "video_id": 1,
                }
            ],
            liked_videos=[
                {
                    "date": base,
                    "link": "https://www.tiktok.com/@user/video/10",
                    "video_id": 10,
                },
                {
                    "date": base,
                    "link": "https://www.tiktok.com/@user/video/20",
                    "video_id": 20,
                },
            ],
            shared_videos=[
                {
                    "date": base,
                    "sharedcontent": "https://www.tiktok.com/@user/video/10",
                    "video_id": 10,
                },
            ],
            video_bookmarks=[
                {
                    "date": base,
                    "link": "https://www.tiktok.com/@user/video/30",
                    "video_id": 30,
                },
            ],
            comments=[
                {
                    "date": base,
                    "link": "https://www.tiktok.com/@user/video/20",
                    "video_id": 20,
                },
            ],
        )
        metrics = compute_engagement_metrics(data, frozenset({10, 20}))
        self.assertEqual(metrics["frac_political_engagement"], 0.8)

    def test_returns_empty_when_no_engagements(self):
        data = TikTokUserData(
            watch_history=[
                {
                    "date": REPORT_FIRST_DATE_TO_INCLUDE,
                    "link": "https://www.tiktok.com/@user/video/1",
                    "video_id": 1,
                }
            ]
        )
        self.assertEqual(
            compute_engagement_metrics(data, frozenset({1})),
            {},
        )


class RateLikeTests(TestCase):
    def test_like_rate_is_likes_divided_by_views(self):
        base = REPORT_FIRST_DATE_TO_INCLUDE
        data = TikTokUserData(
            watch_history=[
                {
                    "date": base + timedelta(seconds=i),
                    "link": f"https://www.tiktok.com/@user/video/{i}",
                    "video_id": i,
                }
                for i in range(4)
            ],
            liked_videos=[
                {
                    "date": base,
                    "link": "https://www.tiktok.com/@user/video/10",
                    "video_id": 10,
                },
                {
                    "date": base,
                    "link": "https://www.tiktok.com/@user/video/20",
                    "video_id": 20,
                },
            ],
        )
        metrics = compute_watch_history_metrics(data)
        self.assertEqual(metrics["rate_like"], 0.5)


class PeakHourShareTests(TestCase):
    def test_same_peak_hour_fraction(self):
        population = [6.0, 6.0, 12.0, 22.0, 6.0]
        self.assertEqual(
            _peak_hour_same_fraction(6, population),
            0.6,
        )

    def test_peak_hour_comparison_uses_share_bars(self):
        row = _build_peak_hour_comparison(6.0, [6.0, 6.0, 12.0, 22.0, 6.0])
        self.assertEqual(row["value_display"], "6:00")
        self.assertEqual(row["chart_user_value"], 0.6)
        self.assertEqual(row["chart_reference_value"], 0.4)
        self.assertEqual(row["chart_user_value_display"], "60.0\u00a0%")
        self.assertEqual(row["chart_reference_value_display"], "40.0\u00a0%")


class ReferenceDemographicFilterTests(TestCase):
    def _sample_comparison(self, value: float = 0.42, mean: float = 0.3) -> dict:
        return {
            "metric": "frac_instant_skip",
            "label": "Anteil Instant-Skips",
            "radar_label": "Anteil Instant-Skips",
            "value": value,
            "value_display": f"{value * 100:.1f} %",
            "percentile": 72.0,
            "reference_mean": mean,
            "reference_mean_display": f"{mean * 100:.1f} %",
            "reference_mean_percentile": 50.0,
            "reference_median": mean,
            "reference_median_display": f"{mean * 100:.1f} %",
            "reference_p25": 0.2,
            "reference_p75": 0.4,
            "reference_min": 0.05,
            "reference_max": 0.75,
            "reference_min_display": "5.0 %",
            "reference_max_display": "75.0 %",
            "radar_user": 72.0,
            "radar_mean": 50.0,
            "is_fraction": True,
        }

    def test_normalizes_invalid_filter_values(self):
        self.assertEqual(normalize_age_group("invalid"), "all")
        self.assertEqual(normalize_gender_filter("invalid"), "any")

    @unittest.skipIf(
        os.getenv("GITHUB_ACTIONS") == "true",
        "Skipping integration test in CI environment",
    )
    def test_female_filter_changes_reference_mean(self):
        comparisons = [self._sample_comparison()]
        filtered = apply_reference_demographic_filter(
            comparisons,
            age_group="all",
            gender="female",
        )
        self.assertEqual(filtered[0]["value"], comparisons[0]["value"])
        self.assertNotEqual(
            filtered[0]["reference_mean"],
            comparisons[0]["reference_mean"],
        )

    @unittest.skipIf(
        os.getenv("GITHUB_ACTIONS") == "true",
        "Skipping integration test in CI environment",
    )
    def test_reference_group_size_respects_filters(self):
        self.assertGreater(reference_group_size("all", "any"), 0)
        self.assertGreater(reference_group_size("under30", "female"), 0)
        self.assertLess(
            reference_group_size("under30", "female"),
            reference_group_size("all", "any"),
        )


# ============================================================
# services — pure helpers
# ============================================================


class GetVideoIdListTests(TestCase):
    def test_returns_empty_for_none(self):
        self.assertEqual(user_metrics._get_video_id_list(None), [])

    def test_returns_empty_for_empty_list(self):
        self.assertEqual(user_metrics._get_video_id_list([]), [])

    def test_filters_records_before_cutoff(self):
        after = REPORT_FIRST_DATE_TO_INCLUDE + timedelta(days=1)
        before = REPORT_FIRST_DATE_TO_INCLUDE - timedelta(days=1)
        data = [
            {"date": after, "video_id": 1},
            {"date": before, "video_id": 2},
        ]
        self.assertEqual(user_metrics._get_video_id_list(data), [1])

    def test_includes_records_on_cutoff(self):
        data = [{"date": REPORT_FIRST_DATE_TO_INCLUDE, "video_id": 9}]
        self.assertEqual(user_metrics._get_video_id_list(data), [9])

    def test_skips_records_with_unparseable_date(self):
        data = [
            {"date": "not a date", "video_id": 1},
            {"date": REPORT_FIRST_DATE_TO_INCLUDE, "video_id": 2},
        ]
        self.assertEqual(user_metrics._get_video_id_list(data), [2])

    def test_skips_records_with_missing_video_id(self):
        data = [
            {"date": REPORT_FIRST_DATE_TO_INCLUDE, "video_id": None},
            {"date": REPORT_FIRST_DATE_TO_INCLUDE},
            {"date": REPORT_FIRST_DATE_TO_INCLUDE, "video_id": 5},
        ]
        self.assertEqual(user_metrics._get_video_id_list(data), [5])

    def test_preserves_duplicates_and_order(self):
        d = REPORT_FIRST_DATE_TO_INCLUDE + timedelta(hours=1)
        data = [
            {"date": d, "video_id": 1},
            {"date": d, "video_id": 2},
            {"date": d, "video_id": 1},
        ]
        self.assertEqual(user_metrics._get_video_id_list(data), [1, 2, 1])


class GetUsernameListTests(TestCase):
    def test_returns_empty_for_none(self):
        self.assertEqual(user_metrics._get_username_list(None), [])

    def test_returns_empty_for_empty_list(self):
        self.assertEqual(user_metrics._get_username_list([]), [])

    def test_extracts_usernames(self):
        data = [{"username": "alice"}, {"username": "bob"}]
        self.assertEqual(user_metrics._get_username_list(data), ["alice", "bob"])

    def test_skips_records_without_username(self):
        data = [{"username": None}, {"username": "alice"}, {}]
        self.assertEqual(user_metrics._get_username_list(data), ["alice"])


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
        party_map, username_map = user_metrics._build_political_video_metadata(
            videos, [], mapping
        )
        self.assertEqual(party_map, {1: "SPD", 2: "CDU/CSU"})
        self.assertEqual(username_map, {1: "alice", 2: "bob"})

    def test_party_account_video_with_unmapped_user_is_skipped(self):
        videos = [self._video(1, "alice"), self._video(2, "stranger")]
        mapping = {"alice": "SPD"}
        party_map, username_map = user_metrics._build_political_video_metadata(
            videos, [], mapping
        )
        self.assertEqual(party_map, {1: "SPD"})
        self.assertEqual(username_map, {1: "alice"})

    def test_non_party_political_videos_map_to_no_party_key(self):
        non_party = [self._video(10, "stranger"), self._video(11, "outsider")]
        party_map, username_map = user_metrics._build_political_video_metadata(
            [], non_party, {}
        )
        self.assertEqual(party_map, {10: NO_PARTY_KEY, 11: NO_PARTY_KEY})
        self.assertEqual(username_map, {10: "stranger", 11: "outsider"})

    def test_non_party_video_without_user_gets_empty_username(self):
        party_map, username_map = user_metrics._build_political_video_metadata(
            [], [self._video(99, None)], {}
        )
        self.assertEqual(party_map, {99: NO_PARTY_KEY})
        self.assertEqual(username_map, {99: ""})

    def test_combines_both_buckets(self):
        party_videos = [self._video(1, "alice")]
        non_party = [self._video(2, "stranger")]
        party_map, username_map = user_metrics._build_political_video_metadata(
            party_videos, non_party, {"alice": "SPD"}
        )
        self.assertEqual(party_map, {1: "SPD", 2: NO_PARTY_KEY})
        self.assertEqual(username_map, {1: "alice", 2: "stranger"})

    def test_returns_empty_maps_for_no_videos(self):
        party_map, username_map = user_metrics._build_political_video_metadata(
            [], [], {}
        )
        self.assertEqual(party_map, {})
        self.assertEqual(username_map, {})


class ComputePartyCountsTests(TestCase):
    def test_counts_per_party_and_bucket_unknown(self):
        result = user_metrics._compute_party_counts(
            seen_video_ids=[1, 1, 2, 99],
            video_party_map={1: "SPD", 2: "CDU/CSU"},
        )
        as_dict = {r["party"]: r["count"] for r in result}
        self.assertEqual(as_dict, {"SPD": 2, "CDU/CSU": 1, NO_PARTY_KEY: 1})

    def test_returns_empty_list_for_no_videos(self):
        self.assertEqual(user_metrics._compute_party_counts([], {}), [])

    def test_all_buckets_to_no_party_when_no_political_videos_seen(self):
        result = user_metrics._compute_party_counts([10, 20], {})
        self.assertEqual(result, [{"party": NO_PARTY_KEY, "count": 2}])

    def test_orders_by_parties_order_constant(self):
        # Input order intentionally reversed vs PARTIES_ORDER.
        result = user_metrics._compute_party_counts(
            seen_video_ids=[1, 2, 3, 4, 99],
            video_party_map={1: "AfD", 2: "SPD", 3: "CDU/CSU", 4: "B90/GRÜNE"},
        )
        self.assertEqual(
            [r["party"] for r in result],
            ["SPD", "CDU/CSU", "B90/GRÜNE", "AfD", NO_PARTY_KEY],
        )

    def test_unknown_party_sorts_after_known_alphabetically(self):
        result = user_metrics._compute_party_counts(
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
        result = user_metrics._compute_daily_party_counts(records, video_party_map)
        self.assertIn({"date": "2026-05-08", "party": "SPD", "count": 2}, result)
        self.assertIn({"date": "2026-05-09", "party": "CDU/CSU", "count": 1}, result)

    def test_sorted_by_date(self):
        records = [
            self._record("2026-06-01", 2),
            self._record("2026-05-08", 1),
            self._record("2026-05-09", 1),
        ]
        result = user_metrics._compute_daily_party_counts(
            records, {1: "SPD", 2: "CDU/CSU"}
        )
        dates = [r["date"] for r in result]
        self.assertEqual(dates, sorted(dates))

    def test_buckets_unmapped_to_no_party(self):
        records = [self._record("2026-05-08", 999)]
        result = user_metrics._compute_daily_party_counts(records, {})
        self.assertEqual(
            result, [{"date": "2026-05-08", "party": NO_PARTY_KEY, "count": 1}]
        )

    def test_skips_records_with_invalid_date_or_missing_video_id(self):
        records = [
            {"date": "not a date", "video_id": 1},
            {"date": datetime(2026, 5, 8, tzinfo=UTC), "video_id": None},
            self._record("2026-05-08", 1),
        ]
        result = user_metrics._compute_daily_party_counts(records, {1: "SPD"})
        self.assertEqual(result, [{"date": "2026-05-08", "party": "SPD", "count": 1}])


class GetTopVideosTests(TestCase):
    def test_returns_videos_sorted_by_view_count_desc(self):
        seen = [1, 2, 2, 3, 3, 3]
        result = user_metrics._get_top_videos(
            seen_pol_video_ids=seen,
            video_party_map={1: "SPD", 2: "CDU/CSU", 3: "Grüne"},
            username_by_video={1: "alice", 2: "bob", 3: "carol"},
            descriptions_by_video={1: "a", 2: "b", 3: "c"},
            n=3,
        )
        self.assertEqual([v["video_id"] for v in result], [3, 2, 1])
        self.assertEqual(result[0]["view_count"], 3)
        self.assertEqual(result[0]["party"], "Grüne")
        self.assertEqual(result[0]["username"], "carol")
        self.assertEqual(result[0]["description"], "c")

    def test_respects_n_limit(self):
        seen = [1, 2, 3, 4, 5, 6, 7]
        result = user_metrics._get_top_videos(seen, {}, {}, {}, n=2)
        self.assertEqual(len(result), 2)

    def test_returns_empty_for_no_seen_videos(self):
        self.assertEqual(user_metrics._get_top_videos([], {}, {}, {}), [])

    def test_description_defaults_to_empty_string_when_missing(self):
        result = user_metrics._get_top_videos([1], {1: "SPD"}, {1: "alice"}, {}, n=1)
        self.assertEqual(result[0]["description"], "")

    def test_username_defaults_to_empty_string_when_missing(self):
        result = user_metrics._get_top_videos([1], {1: "SPD"}, {}, {}, n=1)
        self.assertEqual(result[0]["username"], "")


# ============================================================
# services — DB-touching helpers
# ============================================================


class ExtractUsernameFromLinkTests(TestCase):
    def test_extracts_username_from_standard_link(self):
        self.assertEqual(
            user_metrics._extract_username_from_link(
                "https://www.tiktok.com/@alice/video/12345"
            ),
            "alice",
        )

    def test_returns_none_for_invalid_link(self):
        self.assertIsNone(user_metrics._extract_username_from_link(""))
        self.assertIsNone(
            user_metrics._extract_username_from_link("https://example.com")
        )


class PartyVideosFromWatchHistoryTests(TestCase):
    def test_maps_party_account_videos_from_links(self):
        cutoff = REPORT_FIRST_DATE_TO_INCLUDE + timedelta(days=1)
        watch_history = [
            {
                "date": cutoff,
                "video_id": 99,
                "link": "https://www.tiktok.com/@alice/video/99",
            },
            {
                "date": cutoff,
                "video_id": 100,
                "link": "https://www.tiktok.com/@stranger/video/100",
            },
        ]
        party_map, username_map = user_metrics._party_videos_from_watch_history(
            watch_history, {"alice": "SPD"}
        )
        self.assertEqual(party_map, {99: "SPD"})
        self.assertEqual(username_map, {99: "alice"})

    def test_skips_entries_before_cutoff_or_without_video_id(self):
        watch_history = [
            {
                "date": REPORT_FIRST_DATE_TO_INCLUDE - timedelta(days=1),
                "video_id": 1,
                "link": "https://www.tiktok.com/@alice/video/1",
            },
            {
                "date": REPORT_FIRST_DATE_TO_INCLUDE,
                "link": "https://www.tiktok.com/@alice/video/2",
            },
        ]
        party_map, username_map = user_metrics._party_videos_from_watch_history(
            watch_history, {"alice": "SPD"}
        )
        self.assertEqual(party_map, {})
        self.assertEqual(username_map, {})


class GetDescriptionsByVideoTests(TestCase):
    def setUp(self):
        self.video = TikTokVideo.objects.create(
            id_tiktok=111, added_by=DataOrigins.DONATION
        )
        APIVideoInfos.objects.create(
            video=self.video,
            description="Wichtige Politik Nachrichten",
        )
        self.other_video = TikTokVideo.objects.create(
            id_tiktok=222, added_by=DataOrigins.DONATION
        )

    def test_returns_descriptions_for_matched_videos(self):
        result = user_metrics._get_descriptions_by_video([111, 222])
        self.assertEqual(result[111], "Wichtige Politik Nachrichten")
        self.assertEqual(result[222], "")

    def test_returns_empty_dict_for_no_ids(self):
        self.assertEqual(user_metrics._get_descriptions_by_video([]), {})

    def test_ignores_unknown_video_ids(self):
        result = user_metrics._get_descriptions_by_video([999])
        self.assertEqual(result, {})

    def test_prefers_latest_api_info_with_description(self):
        video = TikTokVideo.objects.create(id_tiktok=333, added_by=DataOrigins.DONATION)
        APIVideoInfos.objects.create(video=video, description="ältere Version")
        latest = APIVideoInfos.objects.create(
            video=video,
            description="neueste Beschreibung",
        )
        APIVideoInfos.objects.filter(pk=latest.pk).update(
            updated_at=datetime.now(tz=UTC) + timedelta(days=1)
        )
        result = user_metrics._get_descriptions_by_video([333])
        self.assertEqual(result[333], "neueste Beschreibung")


# ============================================================
# services — orchestration (DB integration)
# ============================================================


class ComputeReportStatisticsTests(TestCase):
    """End-to-end DB integration tests for compute_user_report_statistics.

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

        APIVideoInfos.objects.create(
            video=self.v_party,
            description="Statement der SPD zum Wahlkampf",
        )
        APIVideoInfos.objects.create(
            video=self.v_nonparty,
            description="Wichtige Politik Nachrichten von stranger",
        )
        APIVideoInfos.objects.create(
            video=self.v_party_pol,
            description="Politik Update von der SPD",
        )

    def _patch_csv(self, mapping: dict[str, str] | None = None):
        return patch.object(
            user_metrics,
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
            result = user_metrics.compute_user_report_metrics(data)

        # v1, v2 and v4 are political; v3 is not.
        self.assertEqual(set(result["seen_pol_video_ids"]), {1, 2, 4})
        self.assertEqual(result["liked_pol_video_ids"], [2])
        # stranger isn't in the CSV, so it doesn't appear in followed_pol_users.
        self.assertEqual(result["followed_pol_users"], ["alice"])
        # Non-party political video descriptions go to the non-party bucket;
        # party-account video descriptions go to the party bucket.
        self.assertEqual(
            result["non_party_hashtags"],
            ["Wichtige Politik Nachrichten von stranger"],
        )
        self.assertEqual(
            sorted(result["party_hashtags"]),
            sorted(
                [
                    "Statement der SPD zum Wahlkampf",
                    "Politik Update von der SPD",
                ]
            ),
        )
        # Total watched includes the neutral video too.
        self.assertEqual(result["videos_seen_count_total"], 4)

    def test_party_account_with_monitored_hashtag_is_not_double_counted(self):
        cutoff = REPORT_FIRST_DATE_TO_INCLUDE + timedelta(days=1)
        data = TikTokUserData(
            watch_history=[{"date": cutoff, "video_id": 4}],
        )
        with self._patch_csv():
            result = user_metrics.compute_user_report_metrics(data)

        # v4 (party-account + monitored hashtag) — counts once, as SPD.
        self.assertEqual(result["seen_pol_video_ids"], [4])
        as_dict = {r["party"]: r["count"] for r in result["party_counts"]}
        self.assertEqual(as_dict, {"SPD": 1})
        # Its description must NOT appear in non_party_hashtags.
        self.assertEqual(result["non_party_hashtags"], [])
        self.assertEqual(
            result["party_hashtags"],
            ["Politik Update von der SPD"],
        )

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
            result = user_metrics.compute_user_report_metrics(data)

        by_id = {v["video_id"]: v for v in result["top_videos"]}
        self.assertEqual(by_id[2]["username"], "stranger")
        self.assertEqual(by_id[2]["party"], NO_PARTY_KEY)
        self.assertEqual(by_id[1]["username"], "alice")
        self.assertEqual(by_id[1]["party"], "SPD")

    def test_top_videos_include_party_account_from_watch_history_link(self):
        """Donated videos without a DB user still count when the link is
        a party account."""
        donation_only_party_video = TikTokVideo.objects.create(
            id_tiktok=5, added_by=DataOrigins.DONATION
        )
        APIVideoInfos.objects.create(
            video=donation_only_party_video,
            description="SPD Wahlkampf ohne DB-User",
        )
        cutoff = REPORT_FIRST_DATE_TO_INCLUDE + timedelta(days=1)
        data = TikTokUserData(
            watch_history=[
                {
                    "date": cutoff,
                    "video_id": 5,
                    "link": "https://www.tiktok.com/@alice/video/5",
                },
                {"date": cutoff, "video_id": 5},
            ],
        )
        with self._patch_csv():
            result = user_metrics.compute_user_report_metrics(data)

        self.assertEqual(result["seen_pol_video_ids"], [5, 5])
        by_id = {v["video_id"]: v for v in result["top_videos"]}
        self.assertEqual(by_id[5]["username"], "alice")
        self.assertEqual(by_id[5]["party"], "SPD")
        self.assertEqual(by_id[5]["description"], "SPD Wahlkampf ohne DB-User")

    def test_handles_completely_empty_user_data(self):
        with self._patch_csv():
            result = user_metrics.compute_user_report_metrics(TikTokUserData())
        self.assertEqual(result["videos_seen_count_total"], 0)
        self.assertEqual(result["seen_pol_video_ids"], [])
        self.assertEqual(result["liked_pol_video_ids"], [])
        self.assertEqual(result["followed_pol_users"], [])
        self.assertEqual(result["party_counts"], [])
        self.assertEqual(result["daily_party_counts"], [])


class GenerateReportStatisticsTests(TestCase):
    @patch.object(services, "compute_user_report_metrics")
    def test_upserts_statistics_to_db(self, mock_compute):
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
        # ParticipantReportStatistics.objects.update_or_create needs a real
        # Participant FK; patch the model call directly to keep this a pure
        # unit test. update_or_create (rather than create) is what keeps
        # retried/re-run task calls from piling up duplicate report rows.
        with patch.object(
            services.ParticipantReportStatistics.objects, "update_or_create"
        ) as mock_upsert:
            mock_upsert.return_value = (MagicMock(), True)
            result = services.generate_user_report_statistics(
                participant, TikTokUserData()
            )

        mock_compute.assert_called_once()
        mock_upsert.assert_called_once()
        kwargs = mock_upsert.call_args.kwargs
        self.assertEqual(kwargs["participant"], participant)
        self.assertEqual(kwargs["defaults"]["videos_seen_count_total"], 5)
        self.assertEqual(kwargs["defaults"]["seen_pol_video_ids"], [1, 2])
        self.assertIs(result, mock_upsert.return_value[0])


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

    def test_top_videos_use_synthetic_embed_urls(self):
        result = factories._synthetic_top_videos([])
        self.assertEqual(len(result), 3)
        self.assertEqual(
            [video["tiktok_url"] for video in result],
            factories.SYNTHETIC_TOP_VIDEO_URLS,
        )
        self.assertEqual(result[0]["username"], "alice_weidel_afd")

    def test_descriptions_by_video_returns_one_entry_per_id(self):
        result = factories._synthetic_descriptions_by_video([1, 2, 3])
        self.assertEqual(set(result), {1, 2, 3})

    def test_post_data_has_one_record_per_account_per_day(self):
        days = 7
        result = factories.get_synthetic_post_data(days=days)
        self.assertEqual(len(result), days * len(factories.SYNTHETIC_POST_PARTIES))
        self.assertEqual(
            {r["party"] for r in result}, set(factories.SYNTHETIC_POST_PARTIES)
        )
        unique_dates = {r["date"] for r in result}
        self.assertEqual(len(unique_dates), days)

    def test_post_data_counts_are_none_zero_or_positive(self):
        result = factories.get_synthetic_post_data(days=30)
        counts = {r["count"] for r in result}
        self.assertTrue(all(c is None or c >= 0 for c in counts))

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

    @unittest.skipIf(
        os.getenv("GITHUB_ACTIONS") == "true",
        "Skipping integration test in CI environment",
    )
    def test_synthetic_behaviour_comparisons_include_political_engagement(self):
        pol_ids = frozenset({1001, 1002, 1003})
        comparisons = factories._synthetic_behaviour_comparisons(pol_ids)
        metrics = {row["metric"] for row in comparisons}
        self.assertIn("frac_political_engagement", metrics)


class BehaviourProfileComparisonTests(TestCase):
    def _sample_comparison(self, percentile: float = 72.0) -> dict:
        return {
            "metric": "frac_instant_skip",
            "label": "Anteil Instant-Skips (< 1 Sek. bis zum nächsten Video)",
            "radar_label": "Anteil Instant-Skips",
            "value": 0.42,
            "value_display": "42.0 %",
            "percentile": percentile,
            "reference_mean": 0.3,
            "reference_mean_display": "30.0 %",
            "reference_mean_percentile": 50.0,
            "reference_median": 0.28,
            "reference_median_display": "28.0 %",
            "reference_p25": 0.2,
            "reference_p75": 0.4,
            "reference_min": 0.05,
            "reference_max": 0.75,
            "reference_min_display": "5.0 %",
            "reference_max_display": "75.0 %",
            "radar_user": percentile,
            "radar_mean": 50.0,
            "is_fraction": True,
        }

    def test_returns_empty_list_when_empty(self):
        self.assertEqual(user_plots.get_behaviour_profile_rows([]), [])

    def test_row_title_is_single_user_sentence_in_teal(self):
        text = user_plots._row_title_text(self._sample_comparison())
        self.assertIn("color: #0cc4b6", text)
        self.assertIn("42.0 %", text)
        self.assertIn("scrollst du direkt weiter", text)
        self.assertNotIn("Teilnehmende", text)

    def test_chart_uses_teal_and_magenta_bars_with_end_labels(self):
        rows = user_plots.get_behaviour_profile_rows([self._sample_comparison()])
        html = rows[0]["chart_html"]
        self.assertIn("#0cc4b6", html)
        self.assertIn("#ff587a", html)
        self.assertIn("42.0", html)
        self.assertIn("30.0", html)

    def test_axis_max_includes_padding_for_end_labels(self):
        self.assertEqual(
            user_plots._metric_axis_max(
                0.42,
                0.3,
                user_display="42.0 %",
                mean_display="30.0 %",
            ),
            0.42 * (1 + max(0.22, 6 * 0.065)),
        )
        self.assertGreater(
            user_plots._metric_axis_max(
                0.42,
                0.3,
                user_display="42.0 %",
                mean_display="30.0 %",
            ),
            0.42,
        )

    def test_hours_title_is_user_sentence_only(self):
        hours = {
            **self._sample_comparison(),
            "metric": "avg_active_hours_per_day",
            "value": 2.5,
            "value_display": "2.50",
            "reference_mean": 1.8,
            "reference_mean_display": "1.80",
            "is_fraction": False,
        }
        title = user_plots._row_title_text(hours)
        self.assertIn("Stunden aktiv", title)
        self.assertIn("2.50", title)
        self.assertNotIn("Videos", title)

    def test_session_length_title_uses_minutes(self):
        session = {
            **self._sample_comparison(),
            "metric": "avg_session_length_sec",
            "value": 180.0,
            "value_display": "3.0 Min.",
            "is_fraction": False,
        }
        title = user_plots._row_title_text(session)
        self.assertIn("3.0 Min.", title)
        self.assertIn("Sessions dauern", title)

    def test_peak_hour_chart_uses_same_and_different_shares(self):
        peak = {
            **self._sample_comparison(),
            "metric": "peak_activity_hour",
            "value": 6.0,
            "value_display": "6:00",
            "reference_mean": 0.4,
            "reference_mean_display": "40.0 %",
            "chart_user_value": 0.6,
            "chart_reference_value": 0.4,
            "chart_user_value_display": "60.0 %",
            "chart_reference_value_display": "40.0 %",
            "is_fraction": True,
        }
        rows = user_plots.get_behaviour_profile_rows([peak])
        html = rows[0]["chart_html"]
        self.assertIn("60.0", html)
        self.assertIn("40.0", html)
        title = user_plots._row_title_text(peak)
        self.assertIn("6:00", title)
        self.assertIn("60.0", title)
        self.assertIn("40.0", title)
        self.assertIn("gleichen Stunde", title)
        self.assertIn("anderen Uhrzeit", title)

    def test_chart_rows_include_all_behaviour_metrics(self):
        hours = {
            **self._sample_comparison(),
            "metric": "avg_active_hours_per_day",
            "value": 2.5,
            "value_display": "2.50",
            "reference_mean": 1.8,
            "reference_mean_display": "1.80",
            "is_fraction": False,
        }
        session = {
            **self._sample_comparison(),
            "metric": "avg_session_length_sec",
            "value": 180.0,
            "value_display": "3.0 Min.",
            "reference_mean": 120.0,
            "reference_mean_display": "2.0 Min.",
            "is_fraction": False,
        }
        rows = user_plots.get_behaviour_profile_rows(
            [
                self._sample_comparison(),
                hours,
                session,
            ]
        )
        self.assertEqual(len(rows), 3)

    def test_slides_group_metrics_into_three_carousel_panels(self):
        comparisons = [
            {
                **self._sample_comparison(),
                "metric": metric,
            }
            for metric in (
                "avg_active_hours_per_day",
                "avg_videos_per_session",
                "avg_session_length_sec",
                "weekend_activity_frac",
                "night_activity_frac",
                "peak_activity_hour",
                "frac_instant_skip",
                "rate_like",
                "frac_political_engagement",
            )
        ]
        slides = user_plots.get_behaviour_profile_slides(comparisons)
        self.assertEqual(len(slides), 3)
        self.assertEqual(len(slides[0]["rows"]), 3)
        self.assertEqual(len(slides[1]["rows"]), 3)
        self.assertEqual(len(slides[2]["rows"]), 3)

    def test_returns_rows_with_chart_and_title(self):
        rows = user_plots.get_behaviour_profile_rows([self._sample_comparison()])
        self.assertEqual(len(rows), 1)
        self.assertIn("behaviour-plot-mount", rows[0]["chart_html"])
        self.assertIn("color: #0cc4b6", rows[0]["title_html"])
        self.assertIn("scrollst du direkt weiter", rows[0]["title_html"])
        self.assertNotIn("description_html", rows[0])

    def test_returns_html_for_legacy_wrapper(self):
        result = user_plots.get_behaviour_profile_comparison(
            [self._sample_comparison()]
        )
        self.assertIsNotNone(result["html"])
        self.assertIn("behaviour-plot-mount", result["html"])


class PartyDistributionPlotTests(TestCase):
    def test_returns_none_html_when_only_no_party_data(self):
        result = user_plots.get_party_distribution_plot_user(
            [{"party": NO_PARTY_KEY, "count": 5}]
        )
        self.assertEqual(result, {"html": None})

    def test_returns_none_html_when_empty(self):
        self.assertEqual(
            user_plots.get_party_distribution_plot_user([]),
            {"html": None},
        )

    def test_returns_html_when_party_data_present(self):
        result = user_plots.get_party_distribution_plot_user(
            [{"party": "SPD", "count": 5}, {"party": "CDU/CSU", "count": 3}]
        )
        self.assertIsNotNone(result["html"])
        self.assertIn("plotly", result["html"].lower())


class TemporalPartyDistributionPlotTests(TestCase):
    def test_returns_none_html_when_empty(self):
        self.assertEqual(
            user_plots.get_temporal_party_distribution_plot_user([]),
            {"html": None},
        )

    def test_returns_none_html_when_only_no_party_records(self):
        result = user_plots.get_temporal_party_distribution_plot_user(
            [{"date": "2026-05-08", "party": NO_PARTY_KEY, "count": 1}]
        )
        self.assertEqual(result, {"html": None})

    def test_returns_html_when_party_records_present(self):
        result = user_plots.get_temporal_party_distribution_plot_user(
            [
                {"date": "2026-05-08", "party": "SPD", "count": 2},
                {"date": "2026-05-09", "party": "SPD", "count": 1},
                {"date": "2026-05-08", "party": "CDU/CSU", "count": 3},
            ]
        )
        self.assertIsNotNone(result["html"])
        self.assertIn("scatter", result["html"])
        self.assertIn("stackgroup", result["html"])


class TemporalPlotXaxisTickvalsTests(TestCase):
    def test_empty(self):
        self.assertEqual(ddcs.reports.plots.utils.temporal_plot_xaxis_tickvals([]), [])

    def test_single_date(self):
        self.assertEqual(
            ddcs.reports.plots.utils.temporal_plot_xaxis_tickvals(["2026-01-01"]),
            ["2026-01-01"],
        )

    def test_short_series_uses_all_dates(self):
        dates = [f"2026-01-{day:02d}" for day in range(1, 8)]
        self.assertEqual(
            ddcs.reports.plots.utils.temporal_plot_xaxis_tickvals(dates), dates
        )

    def test_long_series_always_includes_start_and_end(self):
        dates = [
            (date(2026, 1, 1) + timedelta(days=offset)).isoformat()
            for offset in range(30)
        ]
        tickvals = ddcs.reports.plots.utils.temporal_plot_xaxis_tickvals(dates)
        self.assertEqual(tickvals[0], dates[0])
        self.assertEqual(tickvals[-1], dates[-1])
        self.assertLessEqual(len(tickvals), 7)


class HexToRgbaTests(TestCase):
    def test_converts_with_default_alpha(self):
        self.assertEqual(
            ddcs.reports.plots.utils.hex_to_rgba("#ff8000"), "rgba(255, 128, 0, 0.9)"
        )

    def test_accepts_hex_without_hash(self):
        self.assertEqual(
            ddcs.reports.plots.utils.hex_to_rgba("000000", alpha=0.5),
            "rgba(0, 0, 0, 0.5)",
        )


# ------------------------------------------------------------
# plots.public_plots
# ------------------------------------------------------------


class PostDataDateRangeTests(TestCase):
    def test_range_starts_at_configured_start_date_and_ends_with_lag(self):
        start, end = account_metrics._post_data_date_range()
        self.assertEqual(start, ddcs.reports.config.PUBLIC_POST_DATA_START_DATE)
        expected_end = timezone.now().date() - timedelta(
            days=ddcs.reports.config.PUBLIC_POST_DATA_END_LAG_DAYS
        )
        self.assertEqual(end, expected_end)


class ComputePostDataTests(TestCase):
    def setUp(self):
        self.alice = TikTokUser.objects.create(
            name="alice", added_by=DataOrigins.DONATION
        )

    def _patch_mapping(self, mapping: dict[str, str]):
        return patch.object(
            account_metrics,
            "load_account_party_mapping",
            return_value=mapping,
        )

    def _patch_range(self, start: date, end: date):
        return patch.object(
            account_metrics,
            "_post_data_date_range",
            return_value=(start, end),
        )

    def test_counts_videos_posted_on_each_date(self):
        day = date(2026, 6, 1)
        moment = datetime(2026, 6, 1, 10, tzinfo=UTC)
        v1 = TikTokVideo.objects.create(
            id_tiktok=1,
            user=self.alice,
            added_by=DataOrigins.DONATION,
            inferred_create_time=moment,
        )
        v2 = TikTokVideo.objects.create(
            id_tiktok=2,
            user=self.alice,
            added_by=DataOrigins.DONATION,
            inferred_create_time=moment + timedelta(hours=2),
        )
        APIVideoInfos.objects.create(video=v1, create_time=moment)
        APIVideoInfos.objects.create(video=v2, create_time=moment + timedelta(hours=2))
        with self._patch_mapping({"alice": "SPD"}), self._patch_range(day, day):
            records = account_metrics._compute_post_data()
        self.assertEqual(
            records,
            [{"username": "alice", "party": "SPD", "date": "2026-06-01", "count": 2}],
        )

    def test_zero_posts_with_successful_sync_is_zero_not_none(self):
        day = date(2026, 6, 1)
        SyncAttempt.objects.create(
            user=self.alice, target_date=day, status=SyncAttempt.Status.SUCCESS
        )
        with self._patch_mapping({"alice": "SPD"}), self._patch_range(day, day):
            records = account_metrics._compute_post_data()
        self.assertEqual(records[0]["count"], 0)

    def test_zero_posts_without_successful_sync_is_none(self):
        day = date(2026, 6, 1)
        with self._patch_mapping({"alice": "SPD"}), self._patch_range(day, day):
            records = account_metrics._compute_post_data()
        self.assertIsNone(records[0]["count"])

    def test_failed_sync_attempt_does_not_count_as_synced(self):
        day = date(2026, 6, 1)
        SyncAttempt.objects.create(
            user=self.alice, target_date=day, status=SyncAttempt.Status.RATE_LIMITED
        )
        with self._patch_mapping({"alice": "SPD"}), self._patch_range(day, day):
            records = account_metrics._compute_post_data()
        self.assertIsNone(records[0]["count"])

    def test_builds_one_record_per_account_per_date_in_range(self):
        start, end = date(2026, 6, 1), date(2026, 6, 3)
        mapping = {"alice": "SPD", "bob": "CDU/CSU"}
        with self._patch_mapping(mapping), self._patch_range(start, end):
            records = account_metrics._compute_post_data()
        self.assertEqual(len(records), len(mapping) * 3)
        self.assertEqual({r["username"] for r in records}, set(mapping))


class GetPostDataCacheTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_caches_result_between_calls(self):
        with patch.object(
            account_metrics,
            "_compute_post_data",
            return_value=[{"username": "alice"}],
        ) as mock_compute:
            first = account_metrics.get_post_data()
            second = account_metrics.get_post_data()
        mock_compute.assert_called_once()
        self.assertEqual(first, second)

    def test_force_refresh_recomputes(self):
        with patch.object(
            account_metrics,
            "_compute_post_data",
            side_effect=[["v1"], ["v2"]],
        ) as mock_compute:
            first = account_metrics.get_post_data()
            second = account_metrics.get_post_data(force_refresh=True)
        self.assertEqual(mock_compute.call_count, 2)
        self.assertEqual(first, ["v1"])
        self.assertEqual(second, ["v2"])


class AggregatePartyCountsTests(TestCase):
    def test_sums_counts_per_party_ignoring_none(self):
        records = [
            {"username": "a", "party": "SPD", "date": "2026-06-01", "count": 2},
            {"username": "b", "party": "SPD", "date": "2026-06-02", "count": 3},
            {"username": "c", "party": "CDU/CSU", "date": "2026-06-01", "count": None},
        ]
        result = account_metrics.aggregate_party_counts(records)
        self.assertEqual({r["party"]: r["count"] for r in result}, {"SPD": 5})

    def test_returns_empty_list_for_no_records(self):
        result = account_metrics.aggregate_party_counts([])
        self.assertEqual(result, [])


class AggregateDailyPartyCountsTests(TestCase):
    def test_sums_per_day_and_party_ignoring_none(self):
        records = [
            {"username": "a", "party": "SPD", "date": "2026-06-02", "count": 1},
            {"username": "b", "party": "SPD", "date": "2026-06-02", "count": 2},
            {"username": "a", "party": "SPD", "date": "2026-06-01", "count": 5},
            {"username": "c", "party": "CDU/CSU", "date": "2026-06-01", "count": None},
        ]
        result = account_metrics.aggregate_daily_party_counts(records)
        self.assertEqual(
            result,
            [
                {"date": "2026-06-01", "party": "SPD", "count": 5},
                {"date": "2026-06-02", "party": "SPD", "count": 3},
            ],
        )

    def test_sorted_by_date(self):
        records = [
            {"username": "a", "party": "SPD", "date": "2026-06-02", "count": 1},
            {"username": "a", "party": "SPD", "date": "2026-06-01", "count": 1},
        ]
        result = account_metrics.aggregate_daily_party_counts(records)
        dates = [r["date"] for r in result]
        self.assertEqual(dates, sorted(dates))


class PartyDistributionAllAccountsPlotTests(TestCase):
    def test_returns_none_html_when_empty(self):
        result = public_plots.get_party_distribution_all_accounts([])
        self.assertEqual(result, {"html": None})

    def test_returns_none_html_when_all_counts_are_none(self):
        records = [
            {"username": "a", "party": "SPD", "date": "2026-06-01", "count": None}
        ]
        result = public_plots.get_party_distribution_all_accounts(records)
        self.assertEqual(result, {"html": None})

    def test_returns_html_and_top_party_data(self):
        records = [
            {"username": "a", "party": "SPD", "date": "2026-06-01", "count": 5},
            {"username": "b", "party": "CDU/CSU", "date": "2026-06-01", "count": 2},
        ]
        result = public_plots.get_party_distribution_all_accounts(records)
        self.assertIsNotNone(result["html"])
        self.assertIn("cornerradius", result["html"])
        expected = {"party": "SPD", "value": 5, "color": "#e4454f"}
        self.assertEqual(result["data"], expected)

    def test_falls_back_to_default_color_for_unlisted_party(self):
        records = [
            {
                "username": "a",
                "party": "Sonstige Partei",
                "date": "2026-06-01",
                "count": 1,
            }
        ]
        result = public_plots.get_party_distribution_all_accounts(records)
        self.assertEqual(
            result["data"]["color"], ddcs.reports.plots.utils.PARTY_COLOR_OTHER
        )


class TemporalPartyDistributionAllAccountsPlotTests(TestCase):
    def test_returns_none_html_when_empty(self):
        result = public_plots.get_temporal_party_distribution_all_accounts([])
        self.assertEqual(result, {"html": None})

    def test_returns_none_html_when_all_counts_are_none(self):
        records = [
            {"username": "a", "party": "SPD", "date": "2026-06-01", "count": None}
        ]
        result = public_plots.get_temporal_party_distribution_all_accounts(records)
        self.assertEqual(result, {"html": None})

    def test_returns_html_when_counts_present(self):
        records = [
            {"username": "a", "party": "SPD", "date": "2026-06-01", "count": 2},
            {"username": "a", "party": "SPD", "date": "2026-06-02", "count": 1},
        ]
        result = public_plots.get_temporal_party_distribution_all_accounts(records)
        self.assertIsNotNone(result["html"])
        self.assertIn("scatter", result["html"])
        self.assertIn("stackgroup", result["html"])


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


class BuildDescriptionFrequenciesTests(TestCase):
    def test_counts_frequencies(self):
        result = wordclouds._build_description_frequencies(
            ["Politik ist wichtig", "politik und wahl"]
        )
        self.assertEqual(result["politik"], 2)
        self.assertEqual(result["wahl"], 1)

    def test_excludes_stopwords(self):
        result = wordclouds._build_description_frequencies(["und der die das politik"])
        self.assertNotIn("und", result)
        self.assertNotIn("der", result)
        self.assertIn("politik", result)

    def test_excludes_blocked_tokens(self):
        blocked = next(iter(HASHTAGS_TO_EXCLUDE))
        result = wordclouds._build_description_frequencies([f"politik {blocked} wahl"])
        self.assertNotIn(blocked, result)
        self.assertIn("politik", result)

    def test_drops_emoji_only_tokens(self):
        result = wordclouds._build_description_frequencies(["🇩🇪 politik"])
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
        self.assertIn('viewBox="0 0 800 600"', result["html"])


class GetWordcloudTests(TestCase):
    """Smoke tests for the unified public wordcloud entry point."""

    def test_party_account_returns_html(self):
        result = wordclouds.get_wordcloud(
            ["Politik und Wahl im Bundestag"], is_party_account=True
        )
        self.assertIsNotNone(result["html"])

    def test_noparty_account_returns_html(self):
        result = wordclouds.get_wordcloud(
            ["Politik und Wahl im Bundestag"], is_party_account=False
        )
        self.assertIsNotNone(result["html"])

    def test_returns_none_html_for_empty_input(self):
        self.assertEqual(
            wordclouds.get_wordcloud([], is_party_account=True), {"html": None}
        )


# ============================================================
# views
# ============================================================


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
                    "description": "Politik Nachrichten",
                },
            ],
            "party_hashtags": ["Politik von der SPD"],
            "non_party_hashtags": ["Politik ohne Partei"],
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
        view.kwargs = {"participant_id": "abc123"}
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
            mock_get_wordcloud.side_effect = lambda descriptions, is_party_account: {
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
        mock_get_wordcloud.assert_any_call(
            ["Politik von der SPD"], is_party_account=True
        )
        mock_get_wordcloud.assert_any_call(
            ["Politik ohne Partei"], is_party_account=False
        )

    def test_share_political_is_none_when_no_videos_seen(self):
        view = views.GetReportView()
        view.statistics = self._statistics(
            videos_seen_count_total=0, seen_pol_video_ids=[]
        )
        view.kwargs = {"participant_id": "abc123"}
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

    def test_top_videos_include_tiktok_urls(self):
        view = views.GetReportView()
        view.statistics = self._statistics(
            top_videos=[
                {
                    "video_id": 1,
                    "view_count": 10,
                    "party": "SPD",
                    "description": "Politik und Wahl",
                    "username": "deinespd",
                },
            ],
        )
        view.kwargs = {"participant_id": "abc123"}
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
        self.assertEqual(
            context["top_videos"][0]["tiktok_url"],
            "https://www.tiktok.com/@deinespd/video/1",
        )
        self.assertEqual(
            context["top_videos"][0]["embed_url"],
            "https://www.tiktok.com/player/v1/1?autoplay=0",
        )
        self.assertEqual(
            context["top_videos"][0]["description"],
            "Politik und Wahl",
        )

    def test_top_videos_preserves_input_order(self):
        # services already returns top_videos sorted desc by view_count;
        # the view trusts that order and does not re-sort.
        view = views.GetReportView()
        view.statistics = self._statistics(
            top_videos=[
                {
                    "video_id": 2,
                    "view_count": 9,
                    "party": "SPD",
                    "description": "",
                    "username": "user2",
                },
                {
                    "video_id": 3,
                    "view_count": 5,
                    "party": "SPD",
                    "description": "",
                    "username": "user3",
                },
                {
                    "video_id": 1,
                    "view_count": 2,
                    "party": "SPD",
                    "description": "",
                    "username": "user1",
                },
            ],
        )
        view.kwargs = {"participant_id": "abc123"}
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
        result = context["top_videos"]
        self.assertEqual([v["video_id"] for v in result], [2, 3, 1])


class GetSyntheticReportViewTests(TestCase):
    def test_setup_populates_synthetic_statistics(self):
        request = RequestFactory().get("/report/get/synthetic/")
        view = views.GetSyntheticReportView()
        view.setup(request)
        self.assertIsNotNone(view.statistics.seen_pol_video_ids)
        self.assertIsNotNone(view.statistics.party_counts)


class PublicPlotsDevViewAccessTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.view = PublicPlotsDevView.as_view()

    @override_settings(DEBUG=True)
    def test_debug_true_allows_anonymous(self):
        request = self.factory.get("/")

        request.user = AnonymousUser()

        response = self.view(request)

        self.assertEqual(response.status_code, 200)

    @override_settings(DEBUG=False)
    def test_debug_false_blocks_anonymous(self):
        request = self.factory.get("/")
        request.user = AnonymousUser()

        with self.assertRaises(Http404):
            self.view(request)

    @override_settings(DEBUG=False)
    def test_debug_false_blocks_authenticated_non_superuser(self):
        user = User.objects.create_user(username="regular", password="pw")
        request = self.factory.get("/")
        request.user = user

        with self.assertRaises(Http404):
            self.view(request)

    @override_settings(DEBUG=False)
    def test_debug_false_allows_superuser(self):
        user = User.objects.create_superuser(
            username="admin", password="pw", email="admin@example.com"
        )
        request = self.factory.get("/")
        request.user = user

        response = self.view(request)

        self.assertEqual(response.status_code, 200)

    @override_settings(DEBUG=True)
    def test_debug_true_allows_superuser_too(self):
        user = User.objects.create_superuser(
            username="admin2", password="pw", email="admin2@example.com"
        )
        request = self.factory.get("/")
        request.user = user

        response = self.view(request)

        self.assertEqual(response.status_code, 200)
