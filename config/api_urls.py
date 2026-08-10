"""
URLconf used exclusively for OpenAPI schema generation.
Only include patterns here that should appear in the public API docs —
this deliberately excludes cms (Wagtail) and ddm.
"""

from django.urls import path

from ddcs.metadata.api import TikTokVideoList

urlpatterns = [
    path(
        "metadata/api/v1/tiktok/videos/",
        TikTokVideoList.as_view(),
        name="metadata:tiktokvideo-list",
    ),
]
