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
from django.urls import reverse
from django.views.generic import TemplateView

from ddcs.datadonation.services import get_user_data
from ddcs.reports.behaviour_metrics import (
    apply_reference_demographic_filter,
    normalize_age_group,
    normalize_gender_filter,
    reference_group_label,
    reference_group_size,
)
from ddcs.reports.config import REPORT_FIRST_DATE_TO_INCLUDE
from ddcs.reports.factories import get_synthetic_report_statistics
from ddcs.reports.models import ParticipantReportStatistics
from ddcs.reports.plots import (
    get_behaviour_profile_rows,
    get_behaviour_profile_slides,
    get_party_distribution_plot_user,
    get_temporal_party_distribution_plot_user,
)
from ddcs.reports.services import generate_report_statistics
from ddcs.reports.wordclouds import get_wordcloud


def _behaviour_profile_context(
    behaviour_comparisons: list[dict],
    *,
    age_group: str = "all",
    gender: str = "any",
    behaviour_profile_url: str,
) -> dict[str, Any]:
    age_group = normalize_age_group(age_group)
    gender = normalize_gender_filter(gender)
    filtered_comparisons = apply_reference_demographic_filter(
        behaviour_comparisons,
        age_group=age_group,
        gender=gender,
    )
    group_size = reference_group_size(age_group, gender)
    return {
        "behaviour_comparisons": filtered_comparisons,
        "behaviour_profile_rows": get_behaviour_profile_rows(filtered_comparisons),
        "behaviour_profile_slides": get_behaviour_profile_slides(filtered_comparisons),
        "behaviour_profile_url": behaviour_profile_url,
        "behaviour_age_group": age_group,
        "behaviour_gender": gender,
        "behaviour_reference_group_label": reference_group_label(age_group, gender),
        "behaviour_reference_group_size": group_size,
    }


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

    def _behaviour_profile_url(self) -> str:
        return reverse(
            "reports:behaviour_profile",
            kwargs={"participant_id": self.kwargs["participant_id"]},
        )

    def get_context_data(self, **kwargs) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)

        behaviour_comparisons = self.statistics.behaviour_comparisons
        context.update(
            _behaviour_profile_context(
                behaviour_comparisons,
                behaviour_profile_url=self._behaviour_profile_url(),
            )
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

    def _behaviour_profile_url(self) -> str:
        return reverse("reports:behaviour_profile_synthetic")

    def _get_behaviour_comparisons(self) -> list[dict]:
        return self.statistics.behaviour_comparisons


class BehaviourProfileFilterView(GetReportView):
    template_name = "reports/partials/behaviour_profile_content.html"

    def get_context_data(self, **kwargs) -> dict[str, Any]:
        age_group = normalize_age_group(self.request.GET.get("age_group"))
        gender = normalize_gender_filter(self.request.GET.get("gender"))
        return _behaviour_profile_context(
            self.statistics.behaviour_comparisons,
            age_group=age_group,
            gender=gender,
            behaviour_profile_url=self._behaviour_profile_url(),
        )


class BehaviourProfileFilterSyntheticView(GetSyntheticReportView):
    template_name = "reports/partials/behaviour_profile_content.html"

    def get_context_data(self, **kwargs) -> dict[str, Any]:
        age_group = normalize_age_group(self.request.GET.get("age_group"))
        gender = normalize_gender_filter(self.request.GET.get("gender"))
        return _behaviour_profile_context(
            self.statistics.behaviour_comparisons,
            age_group=age_group,
            gender=gender,
            behaviour_profile_url=self._behaviour_profile_url(),
        )
