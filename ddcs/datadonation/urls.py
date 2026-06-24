from django.urls import include, path

from ddcs.datadonation import views

app_name = "datadonation"
urlpatterns = [
    path("", include("ddcs.datadonation.portability.urls")),
    path(
        "<slug:slug>/datadonation/",
        views.DonationViewDDM.as_view(),
        name="donation_ddm",
    ),
    path(
        "<slug:slug>/survey/",
        views.CustomQuestionnaireView.as_view(),
        name="questionnaire",
    ),
    path(
        "<slug:slug>/debrief/", views.CustomDebriefingView.as_view(), name="debriefing"
    ),
]
