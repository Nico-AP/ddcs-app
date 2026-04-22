from ddm.participation.views import DataDonationView, create_participation_session
from ddm.projects.models import DonationProject
from django.http import Http404, HttpRequest
from django.utils import timezone

from ddcs.datadonation.settings import DDM_TIKTOK_PROJECT_SLUG


class DonationViewDDM(DataDonationView):
    template_name = "datadonation/donation.html"

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
