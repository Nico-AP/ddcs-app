from ddm.participation.models import Participant
from ddm.participation.views import get_participation_session_id
from ddm.projects.models import DonationProject
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from ddcs.datadonation.portability.models import TikTokConnection


def get_main_donation_project() -> DonationProject:
    return DonationProject.objects.get(slug=settings.TIKTOK_DDM_PROJECT_SLUG)


def get_participant_from_session(request: HttpRequest) -> Participant | None:
    """Gets participant from session.

    If participant does not exist, returns None.
    """
    project = get_main_donation_project()
    session_id = get_participation_session_id(project)
    try:
        participant_id = request.session[session_id]["participant_id"]
    except KeyError:
        return None

    return Participant.objects.filter(pk=participant_id).first()


def store_tiktok_connection_in_session(
    request: HttpRequest,
    connection_id: int,
) -> None:
    request.session["tiktok_connection_id"] = connection_id
    request.session.modified = True


def get_tiktok_connection_from_session(
    request: HttpRequest,
) -> TikTokConnection | None:
    connection_id = request.session.get("tiktok_connection_id")
    if not connection_id:
        return None

    try:
        tiktok_connection = TikTokConnection.objects.get(pk=connection_id)
    except TikTokConnection.DoesNotExist:
        tiktok_connection = None
    return tiktok_connection


class ParticipantInSessionMixin:
    """Ensures a participant is present in the session before dispatching.

    If participant exists, it is stored under self.participant.

    If no participant is found in the session (e.g. `participant_id` key is
    missing), the request is redirected to the briefing page.
    """

    participant: Participant

    def dispatch(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        participant = get_participant_from_session(request)
        if not participant:
            return redirect(self.get_no_participant_redirect_url())
        self.participant = participant
        return super().dispatch(request, *args, **kwargs)

    def get_no_participant_redirect_url(self) -> str:
        return reverse(
            "datadonation:portability_briefing",
            kwargs={"slug": settings.TIKTOK_DDM_PROJECT_SLUG},
        )


class ConnectionInSessionMixin:
    """Ensures a TikTokConnection is present in the session before dispatching.

    If connection exists, it is stored under self.connection.
    """

    connection: TikTokConnection

    def dispatch(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        self.connection = get_tiktok_connection_from_session(self.request)
        if not self.connection:
            return redirect(self.get_no_connection_redirect_url())
        return super().dispatch(request, *args, **kwargs)

    def get_no_connection_redirect_url(self) -> str:
        return reverse(
            "datadonation:portability_briefing",
            kwargs={"slug": settings.TIKTOK_DDM_PROJECT_SLUG},
        )
