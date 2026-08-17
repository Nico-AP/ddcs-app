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
    """Fields controlling whether/how an object is monitored via the Research API.

    ``monitor_api`` toggles monitoring on/off. Items with higher
    ``monitoring_priority_api`` are processed first; lower-priority items may
    fall through when API quota runs out. Sync coverage per (item, date) is
    tracked in :class:`SyncAttempt`.
    """

    monitor_api = models.BooleanField(default=False)
    monitoring_priority_api = models.IntegerField(default=0)

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
    keywords = models.ManyToManyField("Keyword", blank=True)

    class Meta:
        verbose_name = "TikTok Video"
        verbose_name_plural = "TikTok Videos"
        indexes = [
            models.Index(fields=["-updated_at"], name="tiktokvideo_updated_at_idx"),
        ]

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
        indexes = [
            models.Index(
                fields=["monitor_api"],
                name="tiktokuser_monitor_api_idx",
            ),
        ]

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


class Keyword(BaseMetadataModel, APIMonitoredMixin):
    """Keywords are used to query the TikTok Research API."""

    name = models.CharField(max_length=255, db_index=True, unique=True)

    def __str__(self) -> str:
        return self.name


# --- Classification ---


class TikTokVideoClassification(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    video = models.ForeignKey(
        "TikTokVideo",
        on_delete=models.CASCADE,
        related_name="classifications",
    )

    is_political = models.BooleanField(default=False)
    stage1_rationale = models.TextField(blank=True)
    entities = models.JSONField(blank=True, null=True, default=list)
    keyword_matches = models.JSONField(blank=True, null=True, default=list)
    classification_ts = models.DateTimeField(null=True, blank=True)
    # created_at received from classifier

    class Meta:
        managed = False  # prevent accidental migrations; enable once it's prod-ready.

    def __str__(self) -> str:
        return f"Classification {self.pk} for video {self.video.id_tiktok}"


# --- API Progress trackers ---


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
        RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"

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


class SyncAttempt(models.Model):
    """Records one Research API sync attempt for an item on a specific day.

    Exactly one of ``user`` or ``hashtag`` is set — that's how the target
    sync_target is discriminated (users are queried by username; hashtags are
    queried as keywords). Multiple rows may exist per (item, target_date):
    every retry appends a new row so error frequency is auditable.

    Used to plan backfills: an (item, target_date) still needs a sync if
    it has no row with ``status=SUCCESS``.
    """

    class Status(models.TextChoices):
        SUCCESS = "success"
        RATE_LIMITED = "rate_limited"
        TIMEOUT = "timeout"
        API_ERROR = "api_error"
        UNKNOWN = "unknown"

    user = models.ForeignKey(
        TikTokUser,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sync_attempts",
    )
    keyword = models.ForeignKey(
        Keyword,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sync_attempts",
        help_text="Target when the item was queried as a keyword.",
    )
    hashtag = models.ForeignKey(
        TikTokHashtag,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sync_attempts",
        help_text="Target when the item was queried as a keyword (hashtag).",
    )  # Hashtag syncing is deprecated and replaced by keyword;
    # kept for backwards compatibility

    target_date = models.DateField(
        help_text="The day the API was queried for (not when the attempt ran)."
    )
    status = models.CharField(max_length=16, choices=Status.choices)
    error_details = models.JSONField(null=True, blank=True)

    attempted_at = models.DateTimeField(auto_now_add=True)
    tracker = models.ForeignKey(
        "ResearchAPIQueryTracker",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sync_attempts",
    )

    class Meta:
        indexes = [
            models.Index(fields=["user", "target_date"]),
            models.Index(fields=["keyword", "target_date"]),
            models.Index(fields=["hashtag", "target_date"]),
            models.Index(fields=["target_date", "status"]),
        ]
        constraints = [
            models.CheckConstraint(
                name="syncattempt_has_exactly_one_target",
                condition=(
                    models.Q(
                        user__isnull=False, keyword__isnull=True, hashtag__isnull=True
                    )
                    | models.Q(
                        user__isnull=True, keyword__isnull=True, hashtag__isnull=False
                    )
                    | models.Q(
                        user__isnull=True, keyword__isnull=False, hashtag__isnull=True
                    )
                ),
            ),
        ]

    def __str__(self) -> str:
        target = self.user or self.hashtag or self.keyword
        return f"{target} @ {self.target_date} [{self.status}]"
