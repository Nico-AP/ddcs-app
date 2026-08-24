from django.urls import include, path

from ddcs.datadonation import views

app_name = "datadonation"
urlpatterns = [
    path("", include("ddcs.datadonation.portability.urls")),
    path("<slug:slug>/briefing/", views.DDCSBriefingView.as_view(), name="briefing"),
    path(
        "<slug:slug>/datenspende/",
        views.DDCSDownloadUploadView.as_view(),
        name="donation_ddm",
    ),
    path(
        "<slug:slug>/fragebogen/",
        views.DDCSQuestionnaireView.as_view(),
        name="questionnaire",
    ),
    path("<slug:slug>/debrief/", views.DDCSDebriefingView.as_view(), name="debriefing"),
    path("tiktok/switch-path/", views.SwitchPathView.as_view(), name="switch_path"),
    path("send-link", views.SendStudyLink.as_view(), name="send_study_link"),
]
