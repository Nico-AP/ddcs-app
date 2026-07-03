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
    path(
        "report/behaviour/get/synthetic/",
        views.BehaviourProfileFilterSyntheticView.as_view(),
        name="behaviour_profile_synthetic",
    ),
    path(
        "report/behaviour/get/<slug:participant_id>/",
        views.BehaviourProfileFilterView.as_view(),
        name="behaviour_profile",
    ),
]
