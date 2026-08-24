"""Report views.

Authentication note: report URLs are guarded by the participant's
``external_id`` — a random 24-character token generated at participation
start (see ``ddm.participation.models.Participant``). The token acts as a
capability: anyone who possesses it can view that participant's report.
This is the intended access model for the donation flow; no additional
session/auth check is required.
"""

import logging
from typing import Any

from ddm.participation.models import Participant
from django.conf import settings
from django.http import FileResponse, Http404, HttpRequest
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from ddcs.datadonation.services import get_user_data
from ddcs.reports.behaviour_metrics import (
    apply_reference_demographic_filter,
    normalize_age_group,
    normalize_gender_filter,
    reference_group_label,
    reference_group_size,
)
from ddcs.reports.config import HASHTAGS_TO_EXCLUDE, REPORT_FIRST_DATE_TO_INCLUDE
from ddcs.reports.factories import (
    get_synthetic_post_data,
    get_synthetic_report_statistics,
)
from ddcs.reports.models import ParticipantReportStatistics
from ddcs.reports.plots.public_plot_images import (
    PUBLIC_PLOT_IMAGE_SLUGS,
    public_plot_image_path,
    write_public_plot_png,
)
from ddcs.reports.plots.public_plots import (
    get_party_distribution_all_accounts,
    get_temporal_party_distribution_all_accounts,
)
from ddcs.reports.plots.user_plots import (
    get_behaviour_profile_rows,
    get_behaviour_profile_slides,
    get_party_distribution_plot_user,
    get_temporal_party_distribution_plot_user,
)
from ddcs.reports.services import generate_user_report_statistics
from ddcs.reports.user_types import assign_user_type
from ddcs.reports.utils import enrich_top_videos_for_embed
from ddcs.reports.wordclouds import get_wordcloud
from ddcs.website.dashboard_export import nationwide_export_meta

logger = logging.getLogger(__name__)

_SYNTHETIC_BEHAVIOUR_SESSION_KEY = "reports_synthetic_behaviour_comparisons"


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
    # Type uses absolute user values from the unfiltered comparisons so age /
    # gender filters never change the merch typology on HTMX refresh.
    return {
        "behaviour_comparisons": filtered_comparisons,
        "behaviour_profile_rows": get_behaviour_profile_rows(filtered_comparisons),
        "behaviour_profile_slides": get_behaviour_profile_slides(filtered_comparisons),
        "behaviour_user_type": assign_user_type(behaviour_comparisons),
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


def _filter_hashtags(hashtags: list[str]) -> list[str]:
    return [tag for tag in hashtags if tag.lower() not in HASHTAGS_TO_EXCLUDE]


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
        return generate_user_report_statistics(self.participant, data)

    def get_top_videos_table_stats(self) -> list[dict]:
        return [
            {
                **video,
                "filtered_hashtags": _filter_hashtags(video.get("hashtags") or []),
            }
            for video in self.statistics.top_videos
        ]

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

        # Top videos carousel
        context["top_videos"] = enrich_top_videos_for_embed(
            self.get_top_videos_table_stats()
        )

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
        statistics = get_synthetic_report_statistics(self.participant)
        # Keep ridge/user behaviour curves stable across filter HTMX updates
        # until the full synthetic report is refreshed.
        self.request.session[_SYNTHETIC_BEHAVIOUR_SESSION_KEY] = (
            statistics.behaviour_comparisons
        )
        self.request.session.modified = True
        return statistics

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

    def setup(self, request: HttpRequest, *args, **kwargs) -> None:
        # Do not regenerate synthetic statistics on filter changes — reuse the
        # comparisons cached when the full synthetic report was last loaded.
        TemplateView.setup(self, request, *args, **kwargs)
        self.participant = self._get_participant()

    def _cached_behaviour_comparisons(self) -> list[dict]:
        cached = self.request.session.get(_SYNTHETIC_BEHAVIOUR_SESSION_KEY)
        if cached is not None:
            return cached

        statistics = get_synthetic_report_statistics(self.participant)
        self.request.session[_SYNTHETIC_BEHAVIOUR_SESSION_KEY] = (
            statistics.behaviour_comparisons
        )
        self.request.session.modified = True
        return statistics.behaviour_comparisons

    def get_context_data(self, **kwargs) -> dict[str, Any]:
        age_group = normalize_age_group(self.request.GET.get("age_group"))
        gender = normalize_gender_filter(self.request.GET.get("gender"))
        return _behaviour_profile_context(
            self._cached_behaviour_comparisons(),
            age_group=age_group,
            gender=gender,
            behaviour_profile_url=self._behaviour_profile_url(),
        )


class DebugOrSuperuserMixin:
    def dispatch(self, request: HttpRequest, *args, **kwargs):  # noqa: ANN201
        if not settings.DEBUG and not (
            request.user.is_authenticated and request.user.is_superuser
        ):
            raise Http404
        return super().dispatch(request, *args, **kwargs)


class PublicPlotsDevView(DebugOrSuperuserMixin, TemplateView):
    """Dev-only view for inspecting the public (cross-account) plot styling
    with synthetic data, without needing a real database of monitored
    accounts. Not linked from production navigation.
    """

    template_name = "reports/public_plots_dev.html"

    def get_context_data(self, **kwargs) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        records = get_synthetic_post_data()
        context["party_distribution_all_accounts"] = (
            get_party_distribution_all_accounts(records)
        )
        context["temporal_party_distribution_all_accounts"] = (
            get_temporal_party_distribution_all_accounts(records)
        )
        context["export_meta"] = nationwide_export_meta()
        context["public_plot_embed_urls"] = {
            "videos_gesamt": self.request.build_absolute_uri(
                reverse("reports:public_plot_png", kwargs={"slug": "videos-gesamt"})
            ),
            "videos_zeit": self.request.build_absolute_uri(
                reverse(
                    "reports:public_plot_png",
                    kwargs={"slug": "videos-ueber-die-zeit"},
                )
            ),
        }
        return context


class PublicPlotPngView(View):
    """Stable PNG URL for embedding the homepage public plots."""

    def get(self, request: HttpRequest, slug: str) -> FileResponse:
        if slug not in PUBLIC_PLOT_IMAGE_SLUGS:
            raise Http404
        path = public_plot_image_path(slug)
        if not path.exists():
            # In production these are written by the daily Celery task; rendering
            # them inside a web request would put chart generation on the request
            # path. Locally there is no beat schedule, so build on first access.
            if not settings.DEBUG:
                logger.warning(
                    "Public plot PNG %s is missing; run the "
                    "refresh_public_plot_images management command.",
                    slug,
                )
                raise Http404
            try:
                write_public_plot_png(slug)
            except (OSError, RuntimeError, ValueError) as exc:
                raise Http404 from exc
        response = FileResponse(path.open("rb"), content_type="image/png")
        response["Cache-Control"] = "public, max-age=3600"
        response["Content-Disposition"] = f'inline; filename="{slug}.png"'
        return response
