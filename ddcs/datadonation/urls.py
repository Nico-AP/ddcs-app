from django.urls import include, path

from ddcs.datadonation import views

app_name = "datadonation"
urlpatterns = [
    path("", include("ddcs.datadonation.portability.urls")),
    path("datadonation/", views.DonationViewDDM.as_view(), name="donation_ddm"),
]
