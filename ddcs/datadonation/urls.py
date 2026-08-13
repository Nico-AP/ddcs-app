from django.urls import include, path

from ddcs.datadonation import views

app_name = "datadonation"
urlpatterns = [
    path("", include("ddcs.datadonation.portability.urls")),
    path("<slug:slug>/briefing/", views.DDCSBriefingView.as_view(), name="briefing"),
    path(
        "<slug:slug>/datadonation/",
        views.DDCSDownloadUploadView.as_view(),
        name="donation_ddm",
    ),
    path(
        "<slug:slug>/survey/",
        views.DDCSQuestionnaireView.as_view(),
        name="questionnaire",
    ),
    path("<slug:slug>/debrief/", views.DDCSDebriefingView.as_view(), name="debriefing"),
]
