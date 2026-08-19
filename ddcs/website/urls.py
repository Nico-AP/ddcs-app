from django.urls import path

from ddcs.website import views

app_name = "website"
urlpatterns = [
    path(
        "2025/",
        views.DFDW2025PageView.as_view(),
        name="dfdw_2025",
    ),
    path(
        "dashboard/public/",
        views.PublicDashboardView.as_view(),
        name="public_dashboard",
    ),
]
