from django.urls import path

from ddcs.metadata.api import TikTokVideoList
from ddcs.metadata.dashboard.views import MetadataDashboardView

app_name = "metadata"
urlpatterns = [
    path("api/v1/tiktok/videos/", TikTokVideoList.as_view(), name="tiktokvideo-list"),
    path("dashboard/", MetadataDashboardView.as_view(), name="dashboard"),
]
