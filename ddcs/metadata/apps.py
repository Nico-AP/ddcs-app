from django.apps import AppConfig


class DDCSMetadataConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ddcs.metadata"
    verbose_name = "DDCS Metadata"
    label = "ddcs_metadata"
