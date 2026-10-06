from datetime import date
from typing import Any

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponseRedirect
from django.views.generic import TemplateView

from ddcs.metadata.dashboard.metrics import (
    default_date_range,
    fill_classification_coverage,
    get_dashboard_snapshot,
    get_monitored_keyword_count,
    get_monitored_user_count,
    get_scraper_queue,
    get_sync_coverage,
)
from ddcs.metadata.dashboard.plots import (
    get_classification_coverage_plot,
    get_origin_counts_plot,
    get_sync_coverage_plot,
)
from ddcs.metadata.tasks import request_dashboard_refresh


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

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponseRedirect:
        """ "Refresh now": queue a recompute, then return to the same range."""
        request_dashboard_refresh()
        return HttpResponseRedirect(request.get_full_path())

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        context = super().get_context_data(**kwargs)
        start, end = self._date_range()
        context["start"] = start
        context["end"] = end

        # The video-level aggregates are far too slow to compute in a
        # request; they come from a snapshot a Celery task keeps warm.
        snapshot = get_dashboard_snapshot()
        if snapshot is None:
            request_dashboard_refresh()
            # With CELERY_TASK_ALWAYS_EAGER (local dev) the task has already
            # run inline, so the snapshot is there now.
            snapshot = get_dashboard_snapshot()
        context["snapshot_computed_at"] = snapshot and snapshot["computed_at"]

        origin_counts = snapshot["origin_counts"] if snapshot else []
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

        classification_coverage = (
            fill_classification_coverage(snapshot["classification_by_date"], start, end)
            if snapshot
            else []
        )
        context["classification_coverage_plot"] = get_classification_coverage_plot(
            classification_coverage
        )

        context["scraper_enabled"] = settings.TIKTOK_SCRAPER_ENABLED
        context["scraper_queue"] = get_scraper_queue()

        return context
