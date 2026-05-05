import logging
from datetime import datetime, timedelta

from authlib.integrations.django_client import OAuthError
from ddm.participation.views import DataDonationView, create_participation_session
from ddm.projects.models import DonationProject
from django.http import Http404, HttpRequest, HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from ddcs.datadonation.portability.models import TikTokConnection
from ddcs.datadonation.portability.oauth import oauth
from ddcs.datadonation.settings import DDM_TIKTOK_PROJECT_SLUG

logger = logging.getLogger(__name__)


class TikTokConnectionView(TemplateView):
    template_name = "datadonation/portability/connection.html"


class TikTokConnectView(View):
    def get(self, request: HttpRequest) -> HttpResponseRedirect:
        """Redirects users to TikTok authentication page."""
        # TODO: Log user out if logged in.

        redirect_uri = request.build_absolute_uri(
            reverse("datadonation:tiktok_callback")
        )
        return oauth.tiktok.authorize_redirect(request, redirect_uri)


class TikTokCallbackView(View):
    def get(self, request: HttpRequest) -> HttpResponseRedirect:
        logger.debug(
            "Callback hit. code=%s state=%s",
            request.GET.get("code"),
            request.GET.get("state"),
        )
        try:
            token = oauth.tiktok.authorize_access_token(request)
        except OAuthError as e:
            logger.exception(
                "OAuth error. error=%s description=%s", e.error, e.description
            )
            return redirect(reverse("datadonation:portability_exception"))

        open_id = token.get("open_id")
        access_token_expires_at = self._get_expiration_date(token["expires_in"])
        refresh_token_expires_at = self._get_expiration_date(
            token["refresh_expires_in"]
        )

        TikTokConnection.objects.update_or_create(
            open_id=open_id,
            defaults={
                "access_token": token["access_token"],
                "access_token_expires_at": access_token_expires_at,
                "refresh_token": token.get("refresh_token", ""),
                "refresh_token_expires_at": refresh_token_expires_at,
                "created_at": timezone.now(),
                "token_type": token.get("token_type", ""),
                "scope": token.get("scope", ""),
            },
        )

        # TODO: Create or retrieve user object and log user in
        #  (if we decide to keep open_id)

        # TODO: Check for existing data requests

        # TODO: Check for existing statistics -> external dependency;
        #  should probably not live here; can be moved if information
        #  can also be derived from data requests

        return redirect(reverse("datadonation:tiktok_await_data"))

    def _get_expiration_date(self, expires_in: int) -> datetime:
        return timezone.now() + timedelta(seconds=expires_in)


class TikTokAwaitDataView(TemplateView):
    template_name = "datadonation/portability/await_download.html"


class CheckDataAvailabilityView(View):
    def get(self, request: HttpRequest) -> None:  # TODO: or should it be post?
        pass


class PortabilityDonationView(DataDonationView):
    template_name = "datadonation/portability/donation.html"

    def _initialize_values(self, request: HttpRequest) -> None:
        """Overwrite project initialization and current step assignment"""
        try:
            self.object = DonationProject.objects.get(slug=DDM_TIKTOK_PROJECT_SLUG)
        except DonationProject.DoesNotExist as e:
            raise Http404 from e

        create_participation_session(request, self.object)
        self.participant = self.get_participant_from_session(request)
        if self.participant.current_step is None or self.participant.current_step < 1:
            self.participant.current_step = 1
            self.participant.start_time = timezone.now()
            self.participant.save()

        # Update DDM step
        self.current_step = 1  # TODO: Check robustness


class PortabilityExceptionView(TemplateView):
    template_name = "datadonation/portability/exception.html"
