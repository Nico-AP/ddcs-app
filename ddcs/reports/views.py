"""Report views.

Authentication note: report URLs are guarded by the participant's
``external_id`` — a random 24-character token generated at participation
start (see ``ddm.participation.models.Participant``). The token acts as a
capability: anyone who possesses it can view that participant's report.
This is the intended access model for the donation flow; no additional
session/auth check is required.
"""

from typing import Any

from ddm.participation.models import Participant
from django.http import Http404, HttpRequest
from django.views.generic import TemplateView

from ddcs.datadonation.services import get_user_data
from ddcs.reports.config import REPORT_FIRST_DATE_TO_INCLUDE
from ddcs.reports.factories import get_synthetic_report_statistics
from ddcs.reports.models import ParticipantReportStatistics
from ddcs.reports.plots import (
    get_behaviour_profile_radar,
    get_party_distribution_plot_user,
    get_temporal_party_distribution_plot_user,
)
from ddcs.reports.services import generate_report_statistics
from ddcs.reports.wordclouds import get_wordcloud


class MainReportView(TemplateView):
    template_name = "reports/base.html"

    def get_context_data(self, **kwargs) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["participant_id"] = self.kwargs["participant_id"]
        return context


class GetReportView(TemplateView):
    template_name = "reports/report_body.html"

    participant: Participant
    statistics: ParticipantReportStatistics

    def setup(self, request: HttpRequest, *args, **kwargs) -> None:
        super().setup(request, *args, **kwargs)
        self.participant = self._get_participant()
        self.statistics = self._get_statistics()

    def _get_participant(self) -> Participant:
        try:
            return Participant.objects.get(external_id=self.kwargs["participant_id"])
        except Participant.DoesNotExist:
            # TODO: Render specific error view.
            msg = "Participant does not exist"
            raise Http404(msg)  # noqa: B904

    def _get_statistics(self) -> ParticipantReportStatistics:
        statistics = (
            ParticipantReportStatistics.objects.filter(participant=self.participant)
            .order_by("-generated_at")
            .first()
        )
        if statistics:
            return statistics
        # No statistics found; compute from donated data.
        data = get_user_data(self.participant)
        return generate_report_statistics(self.participant, data)

    def get_top_videos_table_stats(self) -> list[dict]:
        return list(self.statistics.top_videos)

    def get_context_data(self, **kwargs) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)

        behaviour_comparisons = self.statistics.behaviour_comparisons
        context["behaviour_comparisons"] = behaviour_comparisons
        context["behaviour_profile_radar"] = get_behaviour_profile_radar(
            behaviour_comparisons
        )

        # Intro text
        n_seen_total = int(self.statistics.videos_seen_count_total)
        n_seen_pol = len(self.statistics.seen_pol_video_ids)
        share_pol = (
            round((n_seen_pol / n_seen_total) * 100, 1) if n_seen_total > 0 else None
        )

        context["n_seen_pol_videos"] = n_seen_pol
        context["n_seen_total"] = n_seen_total
        context["share_political"] = share_pol
        context["start_date"] = REPORT_FIRST_DATE_TO_INCLUDE

        # Plots
        context["party_distribution_user"] = get_party_distribution_plot_user(
            self.statistics.party_counts
        )
        context["temporal_party_distribution_user"] = (
            get_temporal_party_distribution_plot_user(
                self.statistics.daily_party_counts
            )
        )

        # Top videos table
        context["top_videos"] = self.get_top_videos_table_stats()

        # Wordclouds
        context["wordcloud_party_user"] = get_wordcloud(
            self.statistics.party_hashtags, is_party_account=True
        )
        context["wordcloud_non_party_user"] = get_wordcloud(
            self.statistics.non_party_hashtags, is_party_account=False
        )

        return context


class GetSyntheticReportView(GetReportView):
    def _get_participant(self) -> Participant:
        return Participant()

    def _get_statistics(self) -> ParticipantReportStatistics:
        return get_synthetic_report_statistics(self.participant)

    def _get_behaviour_comparisons(self) -> list[dict]:
        return self.statistics.behaviour_comparisons
