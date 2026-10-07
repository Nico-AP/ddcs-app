from django.urls import path

from ddcs.metadata.api import TikTokVideoList
from ddcs.metadata.dashboard.views import MetadataDashboardView
from ddcs.metadata.scraper.api import ScrapeResultsView, ScrapeTargetClaimView

app_name = "metadata"
urlpatterns = [
    path("api/v1/tiktok/videos/", TikTokVideoList.as_view(), name="tiktokvideo-list"),
    path(
        "api/v1/tiktok/scrape-targets/claim/",
        ScrapeTargetClaimView.as_view(),
        name="scrapetarget-claim",
    ),
    path(
        "api/v1/tiktok/scrape-targets/results/",
        ScrapeResultsView.as_view(),
        name="scrapetarget-results",
    ),
    path("dashboard/", MetadataDashboardView.as_view(), name="dashboard"),
]
