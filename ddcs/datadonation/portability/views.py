import hashlib
import hmac
import logging
from collections.abc import Generator
from datetime import datetime, timedelta
from typing import Any

from authlib.integrations.django_client import OAuthError
from ddm.datadonation.models import FileUploader
from ddm.participation.services import UploaderConfigService
from ddm.participation.views import BriefingView
from django.conf import settings
from django.contrib.auth.mixins import UserPassesTestMixin
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBase,
    HttpResponseRedirect,
    StreamingHttpResponse,
)
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView
from django_htmx.http import HttpResponseClientRedirect
from requests import Response
from requests.exceptions import RequestException

from ddcs.datadonation.portability.api_specifications import Scopes
from ddcs.datadonation.portability.models import TikTokConnection, TikTokDataRequest
from ddcs.datadonation.portability.oauth import oauth
from ddcs.datadonation.portability.services import (
    download_data_request,
    extract_request_id,
    get_valid_token,
    issue_data_request,
    poll_data_request_status,
)
from ddcs.datadonation.session import (
    ConnectionInSessionMixin,
    ParticipantInSessionMixin,
    get_tiktok_connection_from_session,
    store_tiktok_connection_in_session,
)
from ddcs.datadonation.utils import (
    get_current_step_url,
    get_next_step_url,
    get_participant_log,
)
from ddcs.datadonation.views import DDCSDownloadUploadView

logger = logging.getLogger(__name__)


API_PARTICIPATION_FLOW_STEPS = [
    "datadonation:portability_briefing",
    "datadonation:tiktok_connection",
    "datadonation:portability_donation",
    "datadonation:questionnaire",
    "datadonation:debriefing",
]


def hash_open_id(open_id: str) -> str:
    return hmac.new(
        settings.TIKTOK_OPEN_ID_HASH_SECRET.encode(),
        open_id.encode(),
        hashlib.sha256,
    ).hexdigest()


class DataRequestMixin(ConnectionInSessionMixin):
    """Ensures a TikTokConnection is present in the session and a related
    DataRequest in an allowed status exists.

    By default only TikTok-side active requests are accepted (poll/download).
    Donation overrides this to also accept already-downloaded requests.
    """

    data_request: TikTokDataRequest
    data_request_allowed_statuses: list[str] = TikTokDataRequest.ACTIVE_STATES

    def dispatch(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        self.connection = get_tiktok_connection_from_session(request)
        if not self.connection:
            return redirect(self.get_no_connection_redirect_url())

        try:
            self.data_request = TikTokDataRequest.objects.filter(
                connection=self.connection,
                status__in=self.data_request_allowed_statuses,
            ).latest("issued_at")
        except TikTokDataRequest.DoesNotExist:
            return redirect(reverse("datadonation:tiktok_connection"))

        return super().dispatch(request, *args, **kwargs)


class DDCSPortabilityBriefingView(BriefingView):
    """Renders the briefing page with the infos set in DDM."""

    template_name = "datadonation/briefing.html"

    steps = API_PARTICIPATION_FLOW_STEPS
    step_name = "datadonation:portability_briefing"

    def extra_before_render(self, request: HttpRequest) -> None:
        super().extra_before_render(request)
        log = get_participant_log(self.participant)
        log["modes"]["PAPI"] = timezone.now().isoformat()
        self.participant.save()

    def current_step_url(self) -> str:
        return get_current_step_url(self.steps, self.current_step, self.object.slug)

    def next_step_url(self) -> str:
        return get_next_step_url(self.steps, self.current_step, self.object.slug)


class TikTokConnectionInfosView(ParticipantInSessionMixin, TemplateView):
    """Displays connection information.

    Redirects to `TikTokConnectView` which handles the redirection to TikTok's
    authentication page.
    """

    template_name = "datadonation/portability/connection.html"

    def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        self.log_participant_info()
        return super().get(request, *args, **kwargs)

    def log_participant_info(self) -> None:
        log = get_participant_log(self.participant)
        log["steps"]["papi_tiktok-connection-info_reached"] = timezone.now().isoformat()
        self.participant.save()


class TikTokConnectView(ParticipantInSessionMixin, View):
    """Renders the connection information page."""

    def get(self, request: HttpRequest) -> HttpResponseRedirect:
        """Redirects users to TikTok authentication page."""
        redirect_uri = request.build_absolute_uri(
            reverse("datadonation:tiktok_callback")
        )
        self.log_participant_info()
        return oauth.tiktok.authorize_redirect(request, redirect_uri)

    def log_participant_info(self) -> None:
        log = get_participant_log(self.participant)
        log["steps"]["papi_tiktok-connect_dispatched"] = timezone.now().isoformat()
        self.participant.save()


class TikTokCallbackView(ParticipantInSessionMixin, View):
    """Handles the callback from the TikTok Portability API."""

    def get(self, request: HttpRequest) -> HttpResponseRedirect:
        self.log_participant_info()
        logger.debug(
            "Callback hit. code_present=%s state_present=%s",
            bool(request.GET.get("code")),
            bool(request.GET.get("state")),
        )
        try:
            token = oauth.tiktok.authorize_access_token(request)
        except OAuthError as e:
            logger.exception(
                "OAuth error. error=%s description=%s", e.error, e.description
            )
            return redirect(
                reverse(
                    "datadonation:portability_exception",
                    kwargs={"code": "oauth-failed"},
                )
            )

        connection, connection_created = self._get_or_create_tiktok_connection(token)
        store_tiktok_connection_in_session(request, connection.id)

        if not any(scope in connection.scope for scope in list(Scopes)):
            # Participant has not approved access to their data
            logger.info(
                "Participant has not approved access to any relevant data. "
                "connection_id=%s",
                connection.id,
            )
            return redirect(
                reverse(
                    "datadonation:portability_exception", kwargs={"code": "data-types"}
                )
            )

        if not connection_created:
            data_request = (
                TikTokDataRequest.objects.filter(
                    connection=connection,
                    status__in=TikTokDataRequest.ACTIVE_STATES,
                )
                .order_by("-issued_at")
                .first()
            )

            if data_request:
                return redirect(reverse("datadonation:tiktok_await_data"))

        # Create a data request on TikTok's API
        try:
            request_data = issue_data_request(
                get_valid_token(connection), connection.scope
            )
        except RequestException:
            logger.exception(
                "Failed to issue TikTok data request. connection_id=%s", connection.id
            )
            return redirect(
                reverse(
                    "datadonation:portability_exception",
                    kwargs={"code": "request-failed"},
                )
            )

        request_id = extract_request_id(request_data)
        if not request_id:
            logger.error(
                "TikTok data request returned no request_id. response=%s", request_data
            )
            return redirect(
                reverse(
                    "datadonation:portability_exception", kwargs={"code": "no-request"}
                )
            )

        TikTokDataRequest.objects.create(
            connection=connection,
            request_id=request_id,
        )

        return redirect(reverse("datadonation:tiktok_await_data"))

    def _get_or_create_tiktok_connection(
        self, token: dict
    ) -> tuple[TikTokConnection, bool]:
        open_id: str = token.get("open_id")
        hashed_open_id = hash_open_id(open_id)
        access_token_expires_at = self._get_expiration_date(token["expires_in"])
        refresh_token_expires_at = self._get_expiration_date(
            token["refresh_expires_in"]
        )

        return TikTokConnection.objects.update_or_create(
            open_id=hashed_open_id,
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

    @staticmethod
    def _get_expiration_date(expires_in: int) -> datetime:
        return timezone.now() + timedelta(seconds=expires_in)

    def log_participant_info(self) -> None:
        log = get_participant_log(self.participant)
        log["steps"]["papi_callback_reached"] = timezone.now().isoformat()
        self.participant.save()


class TikTokAwaitDataView(
    ParticipantInSessionMixin, ConnectionInSessionMixin, TemplateView
):
    """Renders a waiting message to the user.

    Polls the data request status in the background by calling
    CheckDownloadAvailabilityView through htmx.
    """

    template_name = "datadonation/portability/await_download.html"

    def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        self.log_participant_info()
        return super().get(request, *args, **kwargs)

    def log_participant_info(self) -> None:
        log = get_participant_log(self.participant)
        if "papi_await-view_reached" not in log["steps"]:
            log["steps"]["papi_await-view_reached"] = timezone.now().isoformat()
            self.participant.save()


class CheckDataAvailabilityView(
    ParticipantInSessionMixin, DataRequestMixin, TemplateView
):
    """Polls the data request status and sends partial template depending on the
    outcome to TikTokAwaitDataView.
    """

    template_name: str

    templates = {
        "pending": "datadonation/portability/partials/_data_download_pending_msg.html",
        "success": "datadonation/portability/partials/_data_download_available_msg.html",  # noqa: E501
    }

    connection: TikTokConnection
    data_request: TikTokDataRequest

    SECONDS_TO_DELAY_INFO = 90

    def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        try:
            request_status_response = poll_data_request_status(
                get_valid_token(self.connection),
                self.data_request.request_id,
            )
        except RequestException:
            logger.warning(
                "Failed to poll TikTok data request status. request_id=%s",
                self.data_request.request_id,
            )
            return self.redirect_to_exception("request-failed")

        try:
            request_status = request_status_response["data"].get("status", "")
        except KeyError:
            logger.exception(
                "Check Data Availability received malformed response. "
                "Must contain 'data'.'status' keys."
                "response=%s",
                request_status_response,
            )
            return self.redirect_to_exception("request-failed")

        if request_status not in TikTokDataRequest.State.values:
            logger.warning(
                "Unrecognized TikTok data request status. "
                "request_id=%s status=%r response=%s",
                self.data_request.request_id,
                request_status,
                request_status_response,
            )
            return self.redirect_to_exception("request-failed")

        if request_status in (
            TikTokDataRequest.State.EXPIRED,
            TikTokDataRequest.State.CANCELLED,
        ):
            logger.warning(
                "Encountered expired data request. request_id=%s status=%r",
                self.data_request.request_id,
                request_status,
            )
            self.data_request.status = request_status
            self.data_request.last_polled = timezone.now()
            self.data_request.save(update_fields=["status", "last_polled"])
            return self.redirect_to_exception("request-expired")

        if request_status not in (
            TikTokDataRequest.State.PENDING,
            TikTokDataRequest.State.READY,
        ):
            # NOT_POLLED/DOWNLOADED are valid model states but are never
            # returned by a live poll of TikTok's API.
            logger.warning(
                "Unexpected TikTok data request status for a live poll. "
                "request_id=%s status=%r",
                self.data_request.request_id,
                request_status,
            )
            return self.redirect_to_exception("request-failed")

        self.data_request.status = request_status
        self.data_request.last_polled = timezone.now()
        self.data_request.save(update_fields=["status", "last_polled"])
        self.set_template_based_on_status(request_status)

        if request_status == TikTokDataRequest.State.READY:
            self.advance_participant_step()

        context = self.get_context_data(**kwargs)
        return render(request, self.template_name, context)

    def redirect_to_exception(self, code: str) -> HttpResponse:
        return HttpResponseClientRedirect(
            reverse("datadonation:portability_exception", kwargs={"code": code})
        )

    def advance_participant_step(self) -> None:
        try:
            position = API_PARTICIPATION_FLOW_STEPS.index(
                "datadonation:tiktok_connection"
            )
        except ValueError:
            position = None

        if self.participant.current_step == position:
            self.participant.current_step += 1
            self.participant.save()

    def set_template_based_on_status(self, request_status: str) -> None:
        if request_status == TikTokDataRequest.State.PENDING:
            self.template_name = self.templates["pending"]
        else:
            self.template_name = self.templates["success"]

    def show_reminder_message(self) -> bool:
        """If a data request takes too long to be delivered by TikTok, a
        reminder message is shown to participants.

        "Too long" is determined by CheckDataAvailabilityView.SECONDS_TO_DELAY_INFO.
        """
        # Determine whether reminder message should be displayed
        show_reminder_msg = False
        if self.template_name == self.templates["pending"]:
            time_to_reminder = timedelta(seconds=self.SECONDS_TO_DELAY_INFO)
            if timezone.now() - self.data_request.issued_at > time_to_reminder:
                show_reminder_msg = True
                log = get_participant_log(self.participant)
                if "papi_await-view_got-delay-info" not in log["steps"]:
                    ts_now = timezone.now().isoformat()
                    log["steps"]["papi_await-view_got-delay-info"] = ts_now
                    self.participant.save()
        return show_reminder_msg

    def get_context_data(self, **kwargs) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "poll_datetime": self.data_request.last_polled,
                "project_slug": settings.TIKTOK_DDM_PROJECT_SLUG,
                # "show_reminder_message": self.show_reminder_message(),  # noqa: ERA001
                # TODO: Enable, once the email handling is sorted out.
            }
        )
        return context


class TikTokDownloadView(ParticipantInSessionMixin, DataRequestMixin, View):
    """Downloads the data from the TikTok Portability API and sends it to the user."""

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponseBase:
        """Downloads and returns the TikTok data as a ZIP file.

        Downloads the data from TikTok's API,
        and returns it as an HTTP response with appropriate
        headers for file download.

        Returns:
             StreamingHttpResponse: A response containing the ZIP file data with
                appropriate content-type and content-disposition headers.

        Raises:
            Http404: If the download fails or data is not available.
            Http502: If downloading fails.
        """

        # Download data
        try:
            data_takeout = download_data_request(
                get_valid_token(self.connection), self.data_request.request_id
            )
        except RequestException:
            logger.exception(
                "Failed to download TikTok data. request_id=%s",
                self.data_request.request_id,
            )
            return HttpResponse("Download Failed", status=502)

        return self.stream_download(data_takeout)

    def stream_download(self, data_takeout: Response) -> StreamingHttpResponse:
        def stream_with_cleanup() -> Generator:
            succeeded = False
            try:
                for chunk in data_takeout.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
                succeeded = True
                logger.info(
                    "TikTok data download succeeded. request_id=%s",
                    self.data_request.request_id,
                )
            except Exception:
                logger.exception(
                    "TikTok data download failed while streaming. request_id=%s",
                    self.data_request.request_id,
                )
                raise
            finally:
                # This runs after streaming completes (or fails)
                self.data_request.download_succeeded = succeeded
                self.data_request.download_attempted = True
                self.data_request.downloaded_at = timezone.now()
                if succeeded:
                    self.data_request.status = TikTokDataRequest.State.DOWNLOADED
                else:
                    self.data_request.status = TikTokDataRequest.State.FAILED
                self.data_request.save()

        streaming_response = StreamingHttpResponse(
            stream_with_cleanup(), content_type="application/zip"
        )
        filename = f"tiktok_data_{self.data_request.request_id}.zip"

        streaming_response["Content-Disposition"] = f'attachment; filename="{filename}"'
        if "Content-Length" in data_takeout.headers:
            streaming_response["Content-Length"] = data_takeout.headers[
                "Content-Length"
            ]

        return streaming_response


class PortabilityDonationView(DataRequestMixin, DDCSDownloadUploadView):
    template_name = "datadonation/portability/donation.html"

    steps = API_PARTICIPATION_FLOW_STEPS
    step_name = "datadonation:portability_donation"
    # Donation runs after the takeout was fetched from TikTok; DOWNLOADED must
    # still be allowed or submit is blocked once tiktok-download.js finishes.
    data_request_allowed_statuses = [
        TikTokDataRequest.State.READY,
        TikTokDataRequest.State.DOWNLOADED,
    ]

    def get_uploader_configs(self) -> list:
        project_uploaders = FileUploader.objects.filter(project=self.object)
        configs = UploaderConfigService.create_configs(
            project_uploaders, self.participant
        )
        # Remove Instructions
        for uploader in configs:
            uploader["instructions"] = []
        return configs

    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)
        context["download_url"] = reverse("datadonation:tiktok_download")
        context["failed_url"] = reverse(
            "datadonation:portability_exception", kwargs={"code": "download-failed"}
        )
        return context

    def current_step_url(self) -> str:
        return get_current_step_url(self.steps, self.current_step, self.object.slug)

    def next_step_url(self) -> str:
        return get_next_step_url(self.steps, self.current_step, self.object.slug)

    def log_participant_info(self) -> None:
        log = get_participant_log(self.participant)
        if "papi_donation_reached" not in log["steps"]:
            log["steps"]["papi_donation_reached"] = timezone.now().isoformat()
            self.participant.save()


class PortabilityDonationViewTest(UserPassesTestMixin, DDCSDownloadUploadView):
    template_name = "datadonation/portability/donation.html"

    def test_func(self) -> bool:
        return self.request.user.is_superuser

    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)
        context["download_url"] = reverse("datadonation:tiktok_download")
        context["failed_url"] = reverse(
            "datadonation:portability_exception", kwargs={"code": "download-failed"}
        )
        return context

    def get_uploader_configs(self) -> list:
        project_uploaders = FileUploader.objects.filter(project=self.object)
        configs = UploaderConfigService.create_configs(
            project_uploaders, self.participant
        )
        # Remove Instructions
        for uploader in configs:
            uploader["instructions"] = []
        return configs


class PortabilityExceptionView(ParticipantInSessionMixin, TemplateView):
    template_name = "datadonation/portability/exception.html"

    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)
        code = self.kwargs.get("code")
        self.log_participant_info(code)

        show_retry = True
        show_dl_ul_continue = True
        match code:
            case "data-types":
                pass
            case "download-failed":
                pass
            case "request-expired":
                show_dl_ul_continue = False
            case "no-request":
                pass
            case "oauth-failed":
                pass
            case "request-failed":
                show_retry = False

        context.update(
            {
                "show_retry": show_retry,
                "show_dl_ul_continuation": show_dl_ul_continue,
                "exception_type": code,
            }
        )
        return context

    def log_participant_info(self, code: str) -> None:
        log = get_participant_log(self.participant)
        log["errors"][code] = timezone.now().isoformat()
        self.participant.save()
