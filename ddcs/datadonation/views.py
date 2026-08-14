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
from ddcs.datadonation.utils import get_current_step_url, get_next_step_url

PARTICIPATION_FLOW_STEPS = [
    "datadonation:briefing",
    "",  # Placeholder to align step-count with PAPI step count
    "datadonation:donation_ddm",
    "datadonation:questionnaire",
    "datadonation:debriefing",
]
# The alignment is needed, to allow the two flows to share the questionnaire
# and debriefing steps.


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

    def set_step_completed(self) -> None:
        """Updates the last_completed_step attribute in current session to
        skip step placeholder."""

        self.participant.current_step += 2
        self.participant.save()

    def current_step_url(self) -> str:
        return get_current_step_url(self.steps, self.current_step, self.object.slug)

    def next_step_url(self) -> str:
        return get_next_step_url(self.steps, self.current_step, self.object.slug)


class DDCSDownloadUploadView(DataDonationView):
    template_name = "datadonation/donation.html"

    steps = PARTICIPATION_FLOW_STEPS
    step_name = "datadonation:donation_ddm"

    def process_uploads(self, files: MultiValueDict) -> None:
        # Let DDM process the uploads normally
        super().process_uploads(files)

        # Trigger post-donation processing pipeline
        post_process_donation(self.participant)

    def current_step_url(self) -> str:
        return get_current_step_url(self.steps, self.current_step, self.object.slug)

    def next_step_url(self) -> str:
        return get_next_step_url(self.steps, self.current_step, self.object.slug)


class DDCSQuestionnaireView(QuestionnaireView):
    template_name = "datadonation/questionnaire.html"

    steps = PARTICIPATION_FLOW_STEPS
    step_name = "datadonation:questionnaire"

    def current_step_url(self) -> str:
        return get_current_step_url(self.steps, self.current_step, self.object.slug)

    def next_step_url(self) -> str:
        return get_next_step_url(self.steps, self.current_step, self.object.slug)


class DDCSDebriefingView(DebriefingView):
    template_name = "datadonation/debriefing.html"

    steps = PARTICIPATION_FLOW_STEPS
    step_name = "datadonation:debriefing"

    def get_context_data(self, **kwargs) -> dict:
        """Inject url parameters in redirect target."""
        context = super().get_context_data(**kwargs)
        context["participant_id"] = self.participant.external_id
        return context

    def current_step_url(self) -> str:
        return get_current_step_url(self.steps, self.current_step, self.object.slug)

    def next_step_url(self) -> str:
        return get_next_step_url(self.steps, self.current_step, self.object.slug)
