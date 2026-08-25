import hashlib
import json
import logging
from smtplib import SMTPException

from ddm.participation.views import (
    BriefingView,
    DataDonationView,
    DebriefingView,
    QuestionnaireView,
)
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.datastructures import MultiValueDict
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.debug import sensitive_variables

from ddcs.datadonation.services import post_process_donation
from ddcs.datadonation.session import ParticipantInSessionMixin
from ddcs.datadonation.utils import (
    get_current_step_url,
    get_next_step_url,
    get_participant_log,
)

logger = logging.getLogger(__name__)

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
        log = get_participant_log(self.participant)
        log["modes"]["DLUL"] = timezone.now().isoformat()
        self.participant.save()

    def set_step_completed(self) -> None:
        """Updates the last_completed_step attribute in current session to
        skip step placeholder."""

        self.participant.current_step += 2
        self.participant.save()

    def current_step_url(self) -> str:
        if self.current_step == 1:
            return reverse("datadonation:tiktok_connection")
        return get_current_step_url(self.steps, self.current_step, self.object.slug)

    def next_step_url(self) -> str:
        return get_next_step_url(self.steps, self.current_step + 1, self.object.slug)


class DDCSDownloadUploadView(DataDonationView):
    template_name = "datadonation/donation.html"

    steps = PARTICIPATION_FLOW_STEPS
    step_name = "datadonation:donation_ddm"

    def process_uploads(self, files: MultiValueDict) -> None:
        # Let DDM process the uploads normally
        super().process_uploads(files)

        # Trigger post-donation processing pipeline
        post_process_donation(self.participant)

    def extra_before_render(self, request: HttpRequest) -> None:
        super().extra_before_render(request)
        self.log_participant_info()

    def log_participant_info(self) -> None:
        log = get_participant_log(self.participant)
        if "dlul_donation_reached" not in log["steps"]:
            log["steps"]["dlul_donation_reached"] = timezone.now().isoformat()
            self.participant.save()

    def current_step_url(self) -> str:
        return get_current_step_url(self.steps, self.current_step, self.object.slug)

    def next_step_url(self) -> str:
        return get_next_step_url(self.steps, self.current_step, self.object.slug)


class DDCSQuestionnaireView(QuestionnaireView):
    template_name = "datadonation/questionnaire.html"

    steps = PARTICIPATION_FLOW_STEPS
    step_name = "datadonation:questionnaire"

    def extra_before_render(self, request: HttpRequest) -> None:
        super().extra_before_render(request)
        log = get_participant_log(self.participant)
        log["steps"]["questionnaire_reached"] = timezone.now().isoformat()
        self.participant.save()

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

    def extra_before_render(self, request: HttpRequest) -> None:
        super().extra_before_render(request)
        log = get_participant_log(self.participant)
        log["steps"]["debriefing_reached"] = timezone.now().isoformat()
        self.participant.save()

    def current_step_url(self) -> str:
        return get_current_step_url(self.steps, self.current_step, self.object.slug)

    def next_step_url(self) -> str:
        return get_next_step_url(self.steps, self.current_step, self.object.slug)


class SwitchPathView(ParticipantInSessionMixin, View):
    def get(self, request: HttpRequest) -> HttpResponse:
        # Log switch
        log = get_participant_log(self.participant)
        log["steps"]["switched_to_dlul"] = timezone.now().isoformat()

        # Send to DLUL path
        self.participant.current_step = PARTICIPATION_FLOW_STEPS.index(
            "datadonation:donation_ddm"
        )
        self.participant.save()

        return redirect(
            reverse(
                "datadonation:donation_ddm",
                kwargs={"slug": settings.TIKTOK_DDM_PROJECT_SLUG},
            )
        )


class SendStudyLink(View):
    """Sends the link to the open report to a given e-mail address.

    NOTE: This view handles sensitive personal data (the recipient's
    email address). It must never be written to logs, error reports,
    or any other persistent store beyond what's required to send the
    message. The `email_address` / `post_data` locals are marked via
    `sensitive_variables` so Django's error-reporting machinery
    (e.g. ADMINS email reports, Sentry, etc.) redacts them from any
    traceback captured here.
    """

    @method_decorator(sensitive_variables("email_address", "post_data"))
    def post(self, request: HttpRequest, *args, **kwargs) -> JsonResponse:
        try:
            post_data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse(
                {"status": "error", "message": "Invalid JSON"}, status=400
            )

        email_address = post_data.get("email", None)

        if not email_address:
            return JsonResponse(
                {"status": "error", "message": "Email required"}, status=400
            )

        if not self.validate_email(email_address):
            return JsonResponse(
                {"status": "error", "message": "Invalid email address"}, status=422
            )

        cache_key = self._rate_limit_key(email_address)

        if not cache.add(cache_key, True, timeout=120):  # noqa: FBT003
            # Return the same success response as a real send, so this
            # endpoint can't be used to probe whether an address was
            # recently requested (or exists) via response differences.
            return JsonResponse({"status": "success"})

        text_content = render_to_string("email/study-reminder.txt")

        try:
            msg = EmailMultiAlternatives(
                subject="Dein Feed, Deine Wahl: Teilnahmelink",
                body=text_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[email_address],
            )
            msg.send()
        except SMTPException:
            # Do NOT include `e` here — some SMTP exceptions embed the
            # recipient address in their message/repr.
            logger.exception("Failed to send study-link email due to an SMTP error.")
            return JsonResponse(
                {"status": "error", "message": "Failed to send email"}, status=500
            )

        return JsonResponse({"status": "success"})

    @staticmethod
    def _rate_limit_key(email: str) -> str:
        digest = hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()
        return f"study_link_cooldown:{digest}"

    def validate_email(self, email: str) -> bool:
        """Check if a string represents a valid email address.

        Args:
            email: The email address to check.

        Returns:
            bool: True if the email is valid, False otherwise.
        """
        try:
            validate_email(email)
            return True  # noqa: TRY300
        except ValidationError:
            return False
