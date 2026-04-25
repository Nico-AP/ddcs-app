from django.apps import AppConfig


class DDCSWebsiteConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ddcs.website"
    verbose_name = "DDCS Website"
    label = "ddcs_website"

    def ready(self) -> None:
        import ddcs.website.rich_text  # noqa: F401, PLC0415
