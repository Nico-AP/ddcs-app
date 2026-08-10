from django.test import TestCase

from ddcs.metadata.models import DataOrigins, Keyword, TikTokHashtag, TikTokVideo
from ddcs.metadata.research_api.models import APIVideoInfos
from ddcs.metadata.research_api.utils.backfill_keywords import backfill_keywords
from ddcs.metadata.research_api.utils.keyword_matching import find_matching_keywords


class FindMatchingKeywordsTests(TestCase):
    @staticmethod
    def _kw(name: str) -> Keyword:
        return Keyword.objects.create(name=name)

    # --- description matching -------------------------------------------

    def test_matches_whole_word_in_description(self):
        kw = self._kw("cat")
        result = find_matching_keywords(
            [kw], description="I have a cat at home", hashtag_names=[]
        )
        self.assertEqual(result, [kw])

    def test_does_not_match_substring_inside_longer_word(self):
        kw = self._kw("cat")
        result = find_matching_keywords(
            [kw], description="this is a category page", hashtag_names=[]
        )
        self.assertEqual(result, [])

    def test_matches_at_start_of_description(self):
        kw = self._kw("cat")
        result = find_matching_keywords(
            [kw], description="cat food is great", hashtag_names=[]
        )
        self.assertEqual(result, [kw])

    def test_matches_at_end_of_description(self):
        kw = self._kw("cat")
        result = find_matching_keywords(
            [kw], description="I really love my cat", hashtag_names=[]
        )
        self.assertEqual(result, [kw])

    def test_case_insensitive_match(self):
        kw = self._kw("CatFood")
        result = find_matching_keywords(
            [kw], description="i love catfood so much", hashtag_names=[]
        )
        self.assertEqual(result, [kw])

    def test_multi_word_keyword_matches_single_space(self):
        kw = self._kw("machine learning")
        result = find_matching_keywords(
            [kw],
            description="a great machine learning model",
            hashtag_names=[],
        )
        self.assertEqual(result, [kw])

    def test_multi_word_keyword_does_not_match_extra_word_between(self):
        kw = self._kw("machine learning")
        result = find_matching_keywords(
            [kw],
            description="machine and learning are different words here",
            hashtag_names=[],
        )
        self.assertEqual(result, [])

    def test_keyword_starting_with_punctuation_matches_correctly(self):
        kw = self._kw("#trend")
        result = find_matching_keywords(
            [kw], description="check out #trend today", hashtag_names=[]
        )
        self.assertEqual(result, [kw])

    def test_keyword_starting_with_punctuation_rejects_when_glued(self):
        kw = self._kw("#trend")
        result = find_matching_keywords(
            [kw], description="#trendy stuff is cool", hashtag_names=[]
        )
        self.assertEqual(result, [])

    def test_keyword_ending_with_punctuation_matches_correctly(self):
        kw = self._kw("co.")
        result = find_matching_keywords(
            [kw], description="acme co. is hiring", hashtag_names=[]
        )
        self.assertEqual(result, [kw])

    def test_regex_special_characters_in_keyword_are_escaped(self):
        kw = self._kw("c++")
        result = find_matching_keywords(
            [kw], description="I love c++ programming", hashtag_names=[]
        )
        self.assertEqual(result, [kw])

    def test_empty_description_no_match(self):
        kw = self._kw("cat")
        result = find_matching_keywords([kw], description="", hashtag_names=[])
        self.assertEqual(result, [])

    def test_none_description_no_match(self):
        kw = self._kw("cat")
        result = find_matching_keywords([kw], description=None, hashtag_names=[])
        self.assertEqual(result, [])

    # --- hashtag matching -------------------------------------------------

    def test_matches_via_hashtag_exact(self):
        kw = self._kw("funny")
        result = find_matching_keywords([kw], description="", hashtag_names=["funny"])
        self.assertEqual(result, [kw])

    def test_hashtag_match_is_case_insensitive(self):
        kw = self._kw("Funny")
        result = find_matching_keywords([kw], description="", hashtag_names=["FUNNY"])
        self.assertEqual(result, [kw])

    def test_hashtag_match_is_exact_not_substring(self):
        kw = self._kw("fun")
        result = find_matching_keywords([kw], description="", hashtag_names=["funny"])
        self.assertEqual(result, [])

    # --- multiple keywords / combined ------------------------------------

    def test_multiple_keywords_only_matching_ones_returned(self):
        cat = self._kw("cat")
        dog = self._kw("dog")
        bird = self._kw("bird")
        result = find_matching_keywords(
            [cat, dog, bird],
            description="I have a cat and a dog",
            hashtag_names=[],
        )
        self.assertCountEqual(result, [cat, dog])

    def test_keyword_matched_via_either_description_or_hashtag(self):
        cat = self._kw("cat")
        dog = self._kw("dog")
        result = find_matching_keywords(
            [cat, dog],
            description="just a random caption",
            hashtag_names=["dog"],
        )
        self.assertEqual(result, [dog])

    def test_no_keywords_returns_empty_list(self):
        result = find_matching_keywords(
            [], description="cats and dogs everywhere", hashtag_names=["dog"]
        )
        self.assertEqual(result, [])

    def test_no_matches_returns_empty_list(self):
        kw = self._kw("elephant")
        result = find_matching_keywords(
            [kw], description="cats and dogs everywhere", hashtag_names=["dog"]
        )
        self.assertEqual(result, [])


class BackfillKeywordsTests(TestCase):
    @staticmethod
    def _video(
        id_tiktok: int, description: str = "", hashtags: list[str] | None = None
    ) -> TikTokVideo:
        video = TikTokVideo.objects.create(
            id_tiktok=id_tiktok,
            added_by=DataOrigins.RESEARCH_API,
        )
        APIVideoInfos.objects.create(video=video, description=description)
        for name in hashtags or []:
            hashtag, _ = TikTokHashtag.objects.get_or_create(
                name=name, defaults={"added_by": DataOrigins.RESEARCH_API}
            )
            video.hashtags.add(hashtag)
        return video

    @staticmethod
    def _kw(name: str, monitor_api: bool = True) -> Keyword:  # noqa: FBT002
        return Keyword.objects.create(name=name, monitor_api=monitor_api)

    # --- basic matching -----------------------------------------------

    def test_links_keyword_matched_via_description(self):
        kw = self._kw("cat")
        video = self._video(1, description="I have a cat")

        created = backfill_keywords([kw])

        self.assertEqual(created, 1)
        self.assertIn(kw, video.keywords.all())

    def test_links_keyword_matched_via_hashtag(self):
        kw = self._kw("funny")
        video = self._video(1, hashtags=["funny"])

        created = backfill_keywords([kw])

        self.assertEqual(created, 1)
        self.assertIn(kw, video.keywords.all())

    def test_does_not_link_unmatched_video(self):
        kw = self._kw("elephant")
        video = self._video(1, description="I have a cat")

        created = backfill_keywords([kw])

        self.assertEqual(created, 0)
        self.assertNotIn(kw, video.keywords.all())

    def test_only_matching_videos_are_linked_others_untouched(self):
        kw = self._kw("cat")
        matching = self._video(1, description="my cat is cute")
        non_matching = self._video(2, description="my dog is cute")

        backfill_keywords([kw])

        self.assertIn(kw, matching.keywords.all())
        self.assertNotIn(kw, non_matching.keywords.all())

    def test_video_can_match_multiple_keywords(self):
        cat = self._kw("cat")
        cute = self._kw("cute")
        video = self._video(1, description="my cat is cute")

        created = backfill_keywords([cat, cute])

        self.assertEqual(created, 2)
        self.assertCountEqual(video.keywords.all(), [cat, cute])

    # --- keywords param handling ---------------------------------------

    def test_empty_keywords_list_returns_zero_and_creates_nothing(self):
        self._video(1, description="my cat is cute")

        created = backfill_keywords([])

        self.assertEqual(created, 0)

    def test_none_keywords_defaults_to_monitored_only(self):
        monitored = self._kw("cat", monitor_api=True)
        unmonitored = self._kw("dog", monitor_api=False)
        video = self._video(1, description="cat and dog")

        created = backfill_keywords(None)

        self.assertEqual(created, 1)
        self.assertIn(monitored, video.keywords.all())
        self.assertNotIn(unmonitored, video.keywords.all())

    def test_no_monitored_keywords_returns_zero(self):
        self._kw("dog", monitor_api=False)
        self._video(1, description="a dog")

        created = backfill_keywords(None)

        self.assertEqual(created, 0)

    # --- idempotency / re-run safety ------------------------------------

    def test_rerun_does_not_duplicate_links(self):
        kw = self._kw("cat")
        video = self._video(1, description="my cat")

        first_run = backfill_keywords([kw])
        second_run = backfill_keywords([kw])

        self.assertEqual(first_run, 1)
        self.assertEqual(second_run, 0)
        self.assertEqual(list(video.keywords.all()), [kw])

    def test_rerun_after_new_keyword_only_adds_new_link(self):
        cat = self._kw("cat")
        video = self._video(1, description="my cat is cute")
        backfill_keywords([cat])

        cute = self._kw("cute")
        second_run = backfill_keywords([cute])

        self.assertEqual(second_run, 1)
        self.assertCountEqual(video.keywords.all(), [cat, cute])

    # --- batching ---------------------------------------------------------

    def test_batching_creates_all_links_across_multiple_flushes(self):
        kw = self._kw("cat")
        videos = [self._video(i, description="my cat") for i in range(1, 6)]

        created = backfill_keywords([kw], batch_size=2)

        self.assertEqual(created, 5)
        for video in videos:
            self.assertIn(kw, video.keywords.all())

    def test_return_value_matches_total_links_created(self):
        cat = self._kw("cat")
        dog = self._kw("dog")
        self._video(1, description="cat and dog")
        self._video(2, description="just a cat")
        self._video(3, description="neither pet")

        created = backfill_keywords([cat, dog], batch_size=1)

        self.assertEqual(created, 3)  # video1: 2 links, video2: 1 link, video3: 0
