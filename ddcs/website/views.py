from typing import Any

from csp.constants import UNSAFE_INLINE
from csp.decorators import csp_update
from django.conf import settings
from django.contrib.auth.mixins import UserPassesTestMixin
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import TemplateView

from ddcs.reports.factories import get_synthetic_post_data
from ddcs.reports.metrics.account_metrics import get_post_data
from ddcs.reports.metrics.public_dashboard import (
    get_donation_stats,
    get_likes_per_party,
    get_monitored_video_stats,
    get_tierzeichen_distribution,
    get_tierzeichen_distribution_historic,
)
from ddcs.reports.plots.public_plots import (
    get_likes_per_video_per_party_plot,
    get_party_distribution_all_accounts,
    get_total_likes_per_party_plot,
    get_total_views_per_party_plot,
    get_views_per_video_per_party_plot,
)
from ddcs.reports.user_types import USER_TYPES
from ddcs.reports.utils import (
    load_account_bundesland_mapping,
    load_account_party_mapping,
)
from ddcs.website.methods_lists import (
    build_methods_lists_xlsx,
    get_methods_lists_payload,
    load_monitored_accounts,
    load_monitored_keywords,
)


# The parts copied from the 2025 website contain a lot of inline styles and sources
#  not worth refactoring.
@method_decorator(
    csp_update({"img-src": "data:", "style-src": UNSAFE_INLINE}), name="dispatch"
)
class DFDW2025PageView(TemplateView):
    template_name = "website/dfdw_2025/base.html"


_SYNTHETIC_PARTY_STATS: list[dict] = [
    {
        "party": "AfD",
        "total_likes": 8_200_000,
        "total_views": 95_000_000,
        "video_count": 920,
        "avg_likes_per_video": 8913.0,
        "avg_views_per_video": 103260.9,
    },
    {
        "party": "SPD",
        "total_likes": 3_100_000,
        "total_views": 42_000_000,
        "video_count": 1100,
        "avg_likes_per_video": 2818.2,
        "avg_views_per_video": 38181.8,
    },
    {
        "party": "CDU/CSU",
        "total_likes": 2_400_000,
        "total_views": 35_000_000,
        "video_count": 980,
        "avg_likes_per_video": 2449.0,
        "avg_views_per_video": 35714.3,
    },
    {
        "party": "B90/GRÜNE",
        "total_likes": 1_800_000,
        "total_views": 28_000_000,
        "video_count": 850,
        "avg_likes_per_video": 2117.6,
        "avg_views_per_video": 32941.2,
    },
    {
        "party": "Linke",
        "total_likes": 1_500_000,
        "total_views": 22_000_000,
        "video_count": 620,
        "avg_likes_per_video": 2419.4,
        "avg_views_per_video": 35483.9,
    },
    {
        "party": "FDP",
        "total_likes": 900_000,
        "total_views": 15_000_000,
        "video_count": 540,
        "avg_likes_per_video": 1666.7,
        "avg_views_per_video": 27777.8,
    },
    {
        "party": "BSW",
        "total_likes": 700_000,
        "total_views": 12_000_000,
        "video_count": 380,
        "avg_likes_per_video": 1842.1,
        "avg_views_per_video": 31578.9,
    },
    {
        "party": "Sonstige",
        "total_likes": 400_000,
        "total_views": 8_000_000,
        "video_count": 440,
        "avg_likes_per_video": 909.1,
        "avg_views_per_video": 18181.8,
    },
]


def _enrich_tierzeichen(dist: list[dict]) -> None:
    """Add pct and image_static to each entry in a tierzeichen distribution."""
    if not dist:
        return
    max_count = max(d["count"] for d in dist)
    for item in dist:
        item["pct"] = round(item["count"] / max(max_count, 1) * 100)
        info = USER_TYPES.get(item["animal_id"])
        item["image_static"] = info["image_static"] if info else ""


class PublicDashboardView(UserPassesTestMixin, TemplateView):
    template_name = "website/public_dashboard.html"

    def test_func(self) -> bool:
        if settings.DEBUG:
            return True
        return self.request.user.is_staff

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        context = super().get_context_data(**kwargs)

        bundesland_map = load_account_bundesland_mapping()
        available_bundeslaender = sorted(
            {v for v in bundesland_map.values() if v not in ("", "Andere")}
        )
        selected_bundesland = self.request.GET.get("bundesland", "")
        context["bundeslaender"] = available_bundeslaender
        context["selected_bundesland"] = selected_bundesland

        tierzeichen_dist = get_tierzeichen_distribution()
        tierzeichen_historic = get_tierzeichen_distribution_historic()
        _enrich_tierzeichen(tierzeichen_dist)
        _enrich_tierzeichen(tierzeichen_historic)

        context["tierzeichen_distribution"] = tierzeichen_dist
        context["tierzeichen_total"] = sum(d["count"] for d in tierzeichen_dist)
        context["tierzeichen_historic"] = tierzeichen_historic
        context["tierzeichen_historic_total"] = sum(
            d["count"] for d in tierzeichen_historic
        )

        if settings.DEBUG:
            context["donation_stats"] = {
                "n_donations": 1284,
                "total_videos_watched": 4_820_000,
                "total_likes": 312_400,
                "avg_likes_per_video": 0.06,
            }
        else:
            context["donation_stats"] = get_donation_stats()

        if selected_bundesland:
            filtered_usernames: set[str] | None = {
                u for u, bl in bundesland_map.items() if bl == selected_bundesland
            }
        else:
            filtered_usernames = None

        party_stats_data = self._get_party_stats(filtered_usernames)
        post_data = self._get_post_data(filtered_usernames)

        context["party_distribution_plot"] = get_party_distribution_all_accounts(
            post_data, compact=True
        )
        context["total_views_plot"] = get_total_views_per_party_plot(
            party_stats_data, compact=True
        )
        context["views_per_video_plot"] = get_views_per_video_per_party_plot(
            party_stats_data, compact=True
        )
        context["total_likes_plot"] = get_total_likes_per_party_plot(
            party_stats_data, compact=True
        )
        context["likes_per_video_plot"] = get_likes_per_video_per_party_plot(
            party_stats_data, compact=True
        )

        if settings.DEBUG:
            context["video_stats"] = {
                "total_videos": 4832,
                "total_likes": 12_500_000,
                "n_accounts": 127,
                "n_days": 45,
                "avg_videos_per_account_day": 0.84,
                "avg_likes_per_video": 2588.4,
                "start_date": "2026-07-01",
                "end_date": "2026-08-14",
            }
        else:
            context["video_stats"] = get_monitored_video_stats(
                usernames_filter=filtered_usernames
            )

        return context

    @staticmethod
    def _filtered_parties(usernames: set[str]) -> set[str]:
        return {load_account_party_mapping().get(u) for u in usernames} - {None}

    @staticmethod
    def _get_party_stats(
        filtered_usernames: set[str] | None,
    ) -> list[dict]:
        if not settings.DEBUG:
            return get_likes_per_party(usernames_filter=filtered_usernames)

        data = _SYNTHETIC_PARTY_STATS
        if filtered_usernames is not None:
            parties = PublicDashboardView._filtered_parties(filtered_usernames)
            data = [r for r in data if r["party"] in parties]
        return data

    @staticmethod
    def _get_post_data(filtered_usernames: set[str] | None) -> list[dict]:
        post_data = get_synthetic_post_data() if settings.DEBUG else get_post_data()
        if filtered_usernames is None:
            return post_data
        if settings.DEBUG:
            parties = PublicDashboardView._filtered_parties(filtered_usernames)
            return [r for r in post_data if r["party"] in parties]
        return [r for r in post_data if r["username"] in filtered_usernames]


class MethodsListsView(TemplateView):
    """Public page listing monitored keywords and accounts (from fixture CSVs)."""

    template_name = "website/methods_lists.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        context = super().get_context_data(**kwargs)
        keywords = load_monitored_keywords()
        accounts = load_monitored_accounts()
        context["keywords"] = keywords
        context["accounts"] = accounts
        context["keyword_count"] = len(keywords)
        context["account_count"] = len(accounts)
        return context


class MethodsListsJsonExportView(View):
    def get(self, request: HttpRequest) -> JsonResponse:
        response = JsonResponse(
            get_methods_lists_payload(),
            json_dumps_params={"ensure_ascii": False, "indent": 2},
        )
        response["Content-Disposition"] = 'attachment; filename="monitored_lists.json"'
        return response


class MethodsListsExcelExportView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        content = build_methods_lists_xlsx()
        response = HttpResponse(
            content,
            content_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )
        response["Content-Disposition"] = 'attachment; filename="monitored_lists.xlsx"'
        return response


# ---- Exception Views ----


def custom_400(request: HttpRequest, exception: Exception) -> HttpResponse:
    template = "exceptions/400.html"
    return render(request, template, status=400)


def custom_403(request: HttpRequest, exception: Exception) -> HttpResponse:
    template = "exceptions/403.html"
    return render(request, template, status=403)


def custom_404(request: HttpRequest, exception: Exception) -> HttpResponse:
    template = "exceptions/404.html"
    return render(request, template, status=404)


def custom_500(request: HttpRequest) -> HttpResponse:
    template = "exceptions/500.html"
    return render(request, template, status=500)
