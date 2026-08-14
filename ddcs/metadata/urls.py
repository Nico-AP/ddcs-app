from django.urls import path

from ddcs.metadata.api import TikTokVideoList

app_name = "metadata"
urlpatterns = [
    path("api/v1/tiktok/videos/", TikTokVideoList.as_view(), name="tiktokvideo-list"),
]
