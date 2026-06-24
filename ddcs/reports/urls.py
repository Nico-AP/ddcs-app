from django.urls import path

from ddcs.reports import views

app_name = "reports"
urlpatterns = [
    path(
        "report/<slug:participant_id>/",
        views.MainReportView.as_view(),
        name="report",
    ),
    path(
        "report/get/synthetic/",
        views.GetSyntheticReportView.as_view(),
        name="get_synthetic_report",
    ),
    path(
        "report/get/<slug:participant_id>/",
        views.GetReportView.as_view(),
        name="get_report",
    ),
]
