from django.apps import AppConfig


class DDCSScraperConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ddcs.metadata.scraper"
    verbose_name = "DDCS Scraper"
    label = "ddcs_metadata_scraper"
