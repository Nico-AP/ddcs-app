from django.apps import AppConfig


class DDCSCoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ddcs.core"
    verbose_name = "DDCS Core Components"
    label = "ddcs_core"
