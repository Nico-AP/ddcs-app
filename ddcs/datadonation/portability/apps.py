from django.apps import AppConfig


class DDCSDataDonationPortabilityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ddcs.datadonation.portability"
    verbose_name = "DDCS Portability API Integration"
    label = "ddcs_portability"
