from django.urls import path

from ddcs.datadonation.portability import views

urlpatterns = [
    path(
        "<slug:slug>/start/",
        views.DDCSPortabilityBriefingView.as_view(),
        name="portability_briefing",
    ),
    path(
        "tiktok/connect/",
        views.TikTokConnectionInfosView.as_view(),
        name="tiktok_connection",
    ),
    path("auth/tiktok/", views.TikTokConnectView.as_view(), name="tiktok_auth"),
    path(
        "auth/tiktok/callback/",
        views.TikTokCallbackView.as_view(),
        name="tiktok_callback",
    ),
    path(
        "auth/tiktok/exception/",
        views.PortabilityExceptionView.as_view(),
        name="portability_exception",
    ),
    path(
        "tiktok/connect/await/",
        views.TikTokAwaitDataView.as_view(),
        name="tiktok_await_data",
    ),
    path(
        "tiktok/connect/check",
        views.CheckDataAvailabilityView.as_view(),
        name="tiktok_check_request",
    ),
    path(
        "tiktok/connect/download",
        views.TikTokDownloadView.as_view(),
        name="tiktok_download",
    ),
    path(
        "connect/<slug:slug>/datenspende/",
        views.PortabilityDonationView.as_view(),
        name="portability_donation",
    ),
]
