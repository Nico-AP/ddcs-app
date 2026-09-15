from ddm.participation.models import Participant
from ddm.participation.views import get_participation_session_id
from ddm.projects.models import DonationProject
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from ddcs.datadonation.portability.models import TikTokConnection

SESSION_KEY_DDM_SLUG = "ddm_project_slug"  # used to store a slug, datetime-str tuple


def get_donation_project(project_slug: str) -> DonationProject:
    """Gets donation project based on passed slug - if slug does not exist,
    falls back to the main project."""
    try:
        return DonationProject.objects.get(slug=project_slug)
    except DonationProject.DoesNotExist:
        return DonationProject.objects.get(slug=settings.TIKTOK_DDM_PROJECT_SLUG)


def get_participant_from_session(
    request: HttpRequest, project_slug: str
) -> Participant | None:
    """Gets participant related to a given project from session.
    If participant does not exist, returns None."""
    project = get_donation_project(project_slug)
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


def store_project_slug_in_session(request: HttpRequest, slug: str) -> None:
    """Stashes the project slug in the session so it survives the
    redirect to TikTok's OAuth flow and back - necessary because the callback URL
    is fixed/not project specific.
    Retrieve it in the callback via `get_project_slug_from_session`.
    """
    request.session[SESSION_KEY_DDM_SLUG] = (slug, timezone.now().isoformat())
    request.session.modified = True


def get_project_slug_from_session(request: HttpRequest) -> str | None:
    """Retrieves the project slug stored in the session (set by
    `store_project_slug_in_session`). Falls back to the default DDM
    project slug if none is stored.
    """
    slug = request.session.get(SESSION_KEY_DDM_SLUG)
    return slug[0] if slug else settings.TIKTOK_DDM_PROJECT_SLUG


class ParticipantInSessionMixin:
    """Ensures a participant is present in the session before dispatching.

    If participant exists, it is stored under self.participant.

    If no participant is found in the session (e.g. `participant_id` key is
    missing), the request is redirected to the briefing page.
    """

    participant: Participant

    def dispatch(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        slug = self.get_ddm_project_slug(self.request)
        participant = get_participant_from_session(request, slug)
        if not participant:
            return redirect(self.get_no_participant_redirect_url())
        self.participant = participant
        return super().dispatch(request, *args, **kwargs)

    def get_ddm_project_slug(self, request: HttpRequest) -> str:
        return (
            getattr(self, "kwargs", {}).get("slug")  # Slug present in url
            or get_project_slug_from_session(request)  # Slug present in session
            or settings.TIKTOK_DDM_PROJECT_SLUG  # Fallback: main project slug
        )

    def get_no_participant_redirect_url(self) -> str:
        slug = self.get_ddm_project_slug(self.request)

        return reverse(
            "datadonation:portability_briefing",
            kwargs={"slug": slug},
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
        if hasattr(self, "participant"):
            slug = self.participant.project.slug
        else:
            slug = settings.TIKTOK_DDM_PROJECT_SLUG

        return reverse(
            "datadonation:portability_briefing",
            kwargs={"slug": slug},
        )
