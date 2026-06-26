from django.db import models


class DataOrigins(models.TextChoices):
    RESEARCH_API = "RESEARCH_API", "Research API"
    SCRAPER = "SCRAPER", "Scraper"
    DONATION = "DONATION", "Donation"
    IMPORT = "IMPORT", "Import"


class BaseMetadataModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    added_by = models.CharField(choices=DataOrigins, max_length=24)

    # Scraping Infos
    scraped_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True


class APIMonitoredMixin(models.Model):
    """Contains fields to control whether/how an object is monitored through the api.

    monitor_api controls whether it is monitored or not.
    Objects with higher monitoring_priority are monitored first; lower priority
        come later and may fall through if api limit is reached.
    """

    monitor_api = models.BooleanField(default=False)
    monitoring_priority_api = models.IntegerField(default=0)
    api_last_monitored_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True


class TikTokVideo(BaseMetadataModel):
    id_tiktok = models.BigIntegerField(unique=True, db_index=True)

    inferred_create_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Create time as inferred from the TikTok ID.",
    )  # Note: Is currently populated by API Service;
    # need to remember to compute this if objects are ever created in other places.

    user = models.ForeignKey(
        "TikTokUser",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    music = models.ForeignKey(
        "TikTokMusic",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    hashtags = models.ManyToManyField("TikTokHashtag", blank=True)

    class Meta:
        verbose_name = "TikTok Video"
        verbose_name_plural = "TikTok Videos"

    def __str__(self) -> str:
        return str(self.id_tiktok)


class TikTokUser(BaseMetadataModel, APIMonitoredMixin):
    name = models.CharField(
        max_length=255, unique=True, db_index=True
    )  # unique user name
    id_tiktok = models.BigIntegerField(db_index=True, null=True, blank=True)

    class Meta:
        verbose_name = "TikTok User"
        verbose_name_plural = "TikTok Users"

    def __str__(self) -> str:
        if self.name:
            return self.name
        if self.id_tiktok:
            return str(self.id_tiktok)
        return f"{self.pk} (pk)"

    def has_api_user_infos(self) -> bool:
        return self.api_infos.exists()


class TikTokMusic(BaseMetadataModel):
    id_tiktok = models.BigIntegerField(unique=True, db_index=True)

    class Meta:
        verbose_name = "TikTok Music"
        verbose_name_plural = "TikTok Music"

    def __str__(self) -> str:
        return f"TikTok Music {self.id_tiktok}"


class TikTokHashtag(BaseMetadataModel, APIMonitoredMixin):
    name = models.CharField(max_length=255, db_index=True, unique=True)
    id_tiktok = models.BigIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "Hashtags"
        verbose_name_plural = "Hashtags"

    def __str__(self) -> str:
        if self.name:
            return self.name
        if self.id_tiktok:
            return str(self.id_tiktok)
        return f"{self.pk} (pk)"


# API Progress trackers


class ResearchAPIQueryTracker(models.Model):
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True)

    query_function = models.CharField(max_length=100)
    query_parameters = models.JSONField()

    query_result = models.JSONField(null=True)

    class Status(models.TextChoices):
        STARTED = "started"
        COMPLETED = "completed"
        SOFT_TIME_LIMIT_EXCEEDED = "soft_time_limit_exceeded"
        FAILED = "failed"
        PARTIAL_FAILURE = "partial_failure"

    query_status = models.CharField(
        max_length=32, choices=Status.choices, default=Status.STARTED
    )

    query_exception_details = models.JSONField(blank=True, null=True)

    class Meta:
        verbose_name = "Research API Query Tracker"
        verbose_name_plural = "Research API Query Trackers"

    def __str__(self) -> str:
        return (
            f"{self.query_function} [{self.query_status}] @ "
            f"{self.start_time:%Y-%m-%d %H:%M}"
        )


class TikTokUserAPISync(models.Model):
    """Tracks which days of data have been fetched from the API per user.

    One record per user/date combination; used to identify gaps in sync history.
    """

    user = models.ForeignKey(
        TikTokUser, on_delete=models.CASCADE, related_name="api_syncs"
    )
    synced_date = models.DateField()  # the day the data is queried for
    synced_at = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=True)

    class Meta:
        unique_together = ("user", "synced_date")

    def __str__(self) -> str:
        return f"{self.user} @ {self.synced_date}"
