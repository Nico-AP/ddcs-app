from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse

from ddcs.datadonation.utils import (
    get_current_step_url,
    get_next_step_url,
    get_step_url,
)

API_PARTICIPATION_FLOW_STEPS = [
    "datadonation:portability_briefing",
    "datadonation:tiktok_connection",
    "datadonation:portability_donation",
    "datadonation:questionnaire",
    "datadonation:debriefing",
]


User = get_user_model()


@override_settings(TIKTOK_DDM_PROJECT_SLUG="tiktok")
class TestUrlUtils(TestCase):
    # Test get_step_url

    def test_resolves_url_with_provided_slug(self):
        # "portability_briefing" requires a slug kwarg
        url = get_step_url(API_PARTICIPATION_FLOW_STEPS, 0, slug="my-project")
        expected = reverse(
            "datadonation:portability_briefing", kwargs={"slug": "my-project"}
        )
        self.assertEqual(url, expected)

    def test_uses_default_slug_from_settings_when_slug_is_none(self):
        url = get_step_url(API_PARTICIPATION_FLOW_STEPS, 0, slug=None)
        expected = reverse(
            "datadonation:portability_briefing", kwargs={"slug": "tiktok"}
        )
        self.assertEqual(url, expected)

    def test_falls_back_to_no_kwargs_when_url_does_not_accept_slug(self):
        # "tiktok_connection" does not accept a slug kwarg -> NoReverseMatch -> fallback
        url = get_step_url(API_PARTICIPATION_FLOW_STEPS, 1, slug="my-project")
        expected = reverse("datadonation:tiktok_connection")
        self.assertEqual(url, expected)

    def test_falls_back_to_no_kwargs_with_default_slug(self):
        url = get_step_url(API_PARTICIPATION_FLOW_STEPS, 1, slug=None)
        expected = reverse("datadonation:tiktok_connection")
        self.assertEqual(url, expected)

    def test_raises_no_reverse_match_for_completely_invalid_step(self):
        steps = ["datadonation:this_view_does_not_exist"]
        with self.assertRaises(NoReverseMatch):
            get_step_url(steps, 0, slug="my-project")

    def test_raises_index_error_for_out_of_range_step(self):
        with self.assertRaises(IndexError):
            get_step_url(API_PARTICIPATION_FLOW_STEPS, 99, slug="my-project")

    # Test get_current_step_url

    def test_returns_url_for_current_step(self):
        url = get_current_step_url(API_PARTICIPATION_FLOW_STEPS, 0, slug="my-project")
        expected = reverse(
            "datadonation:portability_briefing", kwargs={"slug": "my-project"}
        )
        self.assertEqual(url, expected)

    def test_returns_url_for_current_step_without_slug_arg(self):
        url = get_current_step_url(API_PARTICIPATION_FLOW_STEPS, 1, slug=None)
        expected = reverse("datadonation:tiktok_connection")
        self.assertEqual(url, expected)

    # Test get_next_step_url

    def test_returns_url_for_next_step(self):
        # current_step=0 (briefing) -> next is tiktok_connection
        url = get_next_step_url(API_PARTICIPATION_FLOW_STEPS, 0, slug="my-project")
        expected = reverse("datadonation:tiktok_connection")
        self.assertEqual(url, expected)

    def test_next_step_with_default_slug(self):
        url = get_next_step_url(API_PARTICIPATION_FLOW_STEPS, 1, slug=None)
        expected = reverse(
            "datadonation:portability_donation", kwargs={"slug": "tiktok"}
        )
        self.assertEqual(url, expected)

    def test_raises_index_error_when_current_step_is_last(self):
        last_index = len(API_PARTICIPATION_FLOW_STEPS) - 1
        with self.assertRaises(IndexError):
            get_next_step_url(
                API_PARTICIPATION_FLOW_STEPS, last_index, slug="my-project"
            )
