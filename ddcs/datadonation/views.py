from ddm.participation.views import (
    DataDonationView,
    DebriefingView,
    QuestionnaireView,
    create_participation_session,
)
from ddm.projects.models import DonationProject
from django.http import Http404, HttpRequest
from django.utils.datastructures import MultiValueDict

from ddcs.datadonation.config import DDM_TIKTOK_PROJECT_SLUG
from ddcs.datadonation.services import post_process_donation

PARTICIPATION_FLOW_STEPS = [
    "datadonation:donation_ddm",
    "datadonation:questionnaire",
    "datadonation:debriefing",
]


class DonationViewDDM(DataDonationView):
    template_name = "datadonation/donation.html"

    steps = PARTICIPATION_FLOW_STEPS
    step_name = "datadonation:donation_ddm"

    def _initialize_values(self, request: HttpRequest) -> None:
        """Overwrite project initialization and current step assignment."""
        try:
            self.object = DonationProject.objects.get(slug=DDM_TIKTOK_PROJECT_SLUG)
        except DonationProject.DoesNotExist as e:
            raise Http404 from e

        create_participation_session(request, self.object)
        self.participant = self.get_participant_from_session(request)
        self.current_step = self.get_current_step_from_participant(self.participant)

    def process_uploads(self, files: MultiValueDict) -> None:
        # Let DDM process the uploads normally
        super().process_uploads(files)

        # Trigger post-donation processing pipeline
        post_process_donation(self.participant)


class CustomQuestionnaireView(QuestionnaireView):
    steps = PARTICIPATION_FLOW_STEPS
    step_name = "datadonation:questionnaire"


class CustomDebriefingView(DebriefingView):
    template_name = "datadonation/debriefing.html"

    steps = PARTICIPATION_FLOW_STEPS
    step_name = "datadonation:debriefing"

    def get_context_data(self, **kwargs) -> dict:
        """Inject url parameters in redirect target."""
        context = super().get_context_data(**kwargs)
        context["participant_id"] = self.participant.external_id
        return context
