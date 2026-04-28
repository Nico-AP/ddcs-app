from django.apps import AppConfig


class DDCSAuthConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ddcs.auth"
    verbose_name = "DDCS Authentication"
    label = "ddcs_auth"
