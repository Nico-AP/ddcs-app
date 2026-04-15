from django.urls import path

from ddcs.website import views

app_name = "website"
urlpatterns = [
    path(
        "",
        views.LandingPageView.as_view(),
        name="landing_page",
    ),
]
