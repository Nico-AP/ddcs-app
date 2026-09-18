from datetime import date
from typing import Any

from django.conf import settings
from django.http import Http404, HttpRequest
from django.views.generic import TemplateView

from ddcs.metadata.dashboard.metrics import (
    default_date_range,
    get_classification_coverage,
    get_monitored_keyword_count,
    get_monitored_user_count,
    get_sync_coverage,
    get_video_counts_by_origin,
)
from ddcs.metadata.dashboard.plots import (
    get_classification_coverage_plot,
    get_origin_counts_plot,
    get_sync_coverage_plot,
)


class DebugOrSuperuserMixin:
    """Restrict a view to superusers, or to anyone when DEBUG=True.

    Copied from ``ddcs.reports.views.DebugOrSuperuserMixin`` — small enough
    that a cross-app import isn't worth it for one mixin.
    """

    def dispatch(self, request: HttpRequest, *args, **kwargs):  # noqa: ANN201
        if not settings.DEBUG and not (
            request.user.is_authenticated and request.user.is_superuser
        ):
            raise Http404
        return super().dispatch(request, *args, **kwargs)


class MetadataDashboardView(DebugOrSuperuserMixin, TemplateView):
    template_name = "metadata/dashboard.html"

    def _date_range(self) -> tuple[date, date]:
        default_start, default_end = default_date_range()
        start_param = self.request.GET.get("start")
        end_param = self.request.GET.get("end")
        try:
            start = date.fromisoformat(start_param) if start_param else default_start
        except ValueError:
            start = default_start
        try:
            end = date.fromisoformat(end_param) if end_param else default_end
        except ValueError:
            end = default_end
        if start > end:
            start, end = end, start
        return start, end

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        context = super().get_context_data(**kwargs)
        start, end = self._date_range()
        context["start"] = start
        context["end"] = end

        origin_counts = get_video_counts_by_origin()
        context["origin_counts"] = origin_counts
        context["origin_counts_plot"] = get_origin_counts_plot(origin_counts)

        monitored_keywords = get_monitored_keyword_count()
        monitored_users = get_monitored_user_count()
        context["monitored_keywords"] = monitored_keywords
        context["monitored_users"] = monitored_users

        keyword_coverage = get_sync_coverage("keyword", start, end)
        context["keyword_coverage_plot"] = get_sync_coverage_plot(
            keyword_coverage, monitored_count=monitored_keywords
        )

        user_coverage = get_sync_coverage("user", start, end)
        context["user_coverage_plot"] = get_sync_coverage_plot(
            user_coverage, monitored_count=monitored_users
        )

        classification_coverage = get_classification_coverage(start, end)
        context["classification_coverage_plot"] = get_classification_coverage_plot(
            classification_coverage
        )

        return context
