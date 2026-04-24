import logging
from datetime import datetime, timedelta

from authlib.integrations.django_client import OAuthError
from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from ddcs.datadonation.portability.models import TikTokConnection
from ddcs.datadonation.portability.oauth import oauth

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
        try:
            auth_kwargs = {
                "grant_type": "authorization_code",
            }
            token = oauth.tiktok.authorize_access_token(request, **auth_kwargs)
        except OAuthError:
            logger.exception("Experienced an OAuth error.")
            # TODO: Rewire to redirect to download-upload approach as a fallback
            return redirect(reverse("datadonation:portability_exception"))

        open_id = token.get("open_id")
        access_token_expires_at = self._get_expiration_date(token["expires_in"])
        refresh_token_expires_at = self._get_expiration_date(
            token["refresh_expires_in"]
        )

        TikTokConnection.objects.update_or_create(
            defaults={
                "open_id": open_id,
                "access_token": token["access_token"],
                "access_token_expires_at": access_token_expires_at,
                "refresh_token": token.get("refresh_token", ""),
                "refresh_expires_at": refresh_token_expires_at,
                "created_at": timezone.now(),
                "token_type": token.get("token_type", ""),
                "scope": token.get("scope", ""),
            }
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


class PortabilityExceptionView(TemplateView):
    template_name = "datadonation/portability/exception.html"
