from django.urls import path

from ddcs.datadonation.portability import views

urlpatterns = [
    path(
        "connect/tiktok/",
        views.TikTokConnectionView.as_view(),
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
        "connect/tiktok/await/",
        views.TikTokAwaitDataView.as_view(),
        name="tiktok_await_data",
    ),
    path(
        "connect/tiktok/datenspende/",
        views.PortabilityDonationView.as_view(),
        name="portability_donation",
    ),
]
