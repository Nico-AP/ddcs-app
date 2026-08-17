from unittest.mock import MagicMock, patch

from ddm.participation.models import Participant
from ddm.participation.views import get_participation_session_id
from ddm.projects.models import DonationProject, ResearchProfile
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ddcs.datadonation.utils import get_participant_log
from ddcs.datadonation.views import PARTICIPATION_FLOW_STEPS


def _dummy_webpack_loader(_config_name):
    # ci settings don't configure WEBPACK_LOADER (only local/production do,
    # pointing at a real webpack-stats.json), so donation_ddm's full render
    # (which needs it for the uploader bundle) needs a stand-in loader for
    # the one test below that renders past the redirect.
    loader = MagicMock()
    loader.config = {}
    loader.get_bundle.return_value = []
    return loader


class SwitchPathViewTest(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="researcher", password="test-pass"
        )
        owner_profile = ResearchProfile.objects.create(user=user)
        self.project = DonationProject.objects.create(
            name="TikTok",
            slug=settings.TIKTOK_DDM_PROJECT_SLUG,
            contact_information="test@example.com",
            data_protection_statement="test",
            owner=owner_profile,
        )
        self.participant = Participant.objects.create(
            project=self.project,
            external_id="x" * 24,
            start_time=timezone.now(),
        )
        session = self.client.session
        session_id = get_participation_session_id(self.project)
        session[session_id] = {"participant_id": self.participant.id}
        session.save()

    def _switch_url(self):
        return reverse("datadonation:switch_path")

    def _donation_ddm_url(self):
        return reverse(
            "datadonation:donation_ddm",
            kwargs={"slug": settings.TIKTOK_DDM_PROJECT_SLUG},
        )

    def test_redirects_to_donation_ddm(self):
        response = self.client.get(self._switch_url())
        self.assertRedirects(
            response, self._donation_ddm_url(), fetch_redirect_response=False
        )

    def test_sets_current_step_to_dlul_donation_step_regardless_of_start(self):
        expected_step = PARTICIPATION_FLOW_STEPS.index("datadonation:donation_ddm")

        for starting_step in (None, 0, 1, 2, 3):
            with self.subTest(starting_step=starting_step):
                self.participant.current_step = starting_step
                self.participant.save()

                self.client.get(self._switch_url())

                self.participant.refresh_from_db()
                self.assertEqual(self.participant.current_step, expected_step)

    def test_persists_switched_to_dlul_log_entry(self):
        self.client.get(self._switch_url())

        self.participant.refresh_from_db()
        log = get_participant_log(self.participant)
        self.assertIn("switched_to_dlul", log["steps"])

    @patch("webpack_loader.utils.get_loader", side_effect=_dummy_webpack_loader)
    def test_donation_ddm_renders_after_switch_without_crashing(self, mock_loader):
        self.participant.current_step = 1
        self.participant.save()

        self.client.get(self._switch_url())
        response = self.client.get(self._donation_ddm_url())

        self.assertEqual(response.status_code, 200)
