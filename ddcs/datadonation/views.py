from ddm.participation.views import (
    BriefingView,
    DataDonationView,
    DebriefingView,
    QuestionnaireView,
)
from django.http import HttpRequest
from django.utils import timezone
from django.utils.datastructures import MultiValueDict

from ddcs.datadonation.services import post_process_donation

PARTICIPATION_FLOW_STEPS = [
    "datadonation:briefing",
    "datadonation:donation_ddm",
    "datadonation:questionnaire",
    "datadonation:debriefing",
]


class DDCSBriefingView(BriefingView):
    template_name = "datadonation/briefing.html"

    steps = PARTICIPATION_FLOW_STEPS
    step_name = "datadonation:briefing"

    def extra_before_render(self, request: HttpRequest) -> None:
        super().extra_before_render(request)
        self.participant.extra_data["participation_mode"] = {
            "DLUL": timezone.now().isoformat(),
        }
        self.participant.save()


class DDCSDownloadUploadView(DataDonationView):
    template_name = "datadonation/donation.html"

    steps = PARTICIPATION_FLOW_STEPS
    step_name = "datadonation:donation_ddm"

    def process_uploads(self, files: MultiValueDict) -> None:
        # Let DDM process the uploads normally
        super().process_uploads(files)

        # Trigger post-donation processing pipeline
        post_process_donation(self.participant)


class DDCSQuestionnaireView(QuestionnaireView):
    template_name = "datadonation/questionnaire.html"

    steps = PARTICIPATION_FLOW_STEPS
    step_name = "datadonation:questionnaire"


class DDCSDebriefingView(DebriefingView):
    template_name = "datadonation/debriefing.html"

    steps = PARTICIPATION_FLOW_STEPS
    step_name = "datadonation:debriefing"

    def get_context_data(self, **kwargs) -> dict:
        """Inject url parameters in redirect target."""
        context = super().get_context_data(**kwargs)
        context["participant_id"] = self.participant.external_id
        return context
