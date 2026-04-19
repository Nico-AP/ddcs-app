from django.urls import path

from ddcs.website import views

app_name = "website"
urlpatterns = [
    path(
        "",
        views.LandingPageView.as_view(),
        name="landing_page",
    ),
    path(
        "impressum/",
        views.ImpressumView.as_view(),
        name="impressum",
    ),
    path(
        "datenschutz/",
        views.DataProtectionStatementView.as_view(),
        name="dps",
    ),
    path(
        "2025/",
        views.DFDW2025PageView.as_view(),
        name="dfdw_2025",
    ),
]
