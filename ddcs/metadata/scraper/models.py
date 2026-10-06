from django.db import models


class ScrapeTarget(models.Model):
    """Queue entry: one TikTok video that should be scraped.

    Only videos worth scraping get a row here, so picking the next batch
    never has to look at the (very large) ``TikTokVideo`` table. Rows are
    created through :func:`ddcs.metadata.scraper.service.enqueue_videos`
    and worked off by :class:`ddcs.metadata.scraper.service.ScraperService`.
    """

    class Status(models.TextChoices):
        PENDING = "pending"
        SUCCESS = "success"
        # TikTok reports the video as gone/private; retrying won't help.
        UNAVAILABLE = "unavailable"
        # The Research API delivered the video in the meantime.
        COVERED_BY_API = "covered_by_api"
        # Retried until ``TIKTOK_SCRAPER_MAX_ATTEMPTS`` is reached.
        FAILED = "failed"

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    video = models.OneToOneField(
        "ddcs_metadata.TikTokVideo",
        on_delete=models.CASCADE,
        related_name="scrape_target",
    )

    inferred_create_time = models.DateTimeField(
        help_text=(
            "Publish time inferred from the video's TikTok ID. "
            "Newest targets are scraped first."
        )
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    attempts = models.PositiveIntegerField(default=0)
    last_attempted_at = models.DateTimeField(null=True, blank=True)

    last_error_type = models.CharField(max_length=255, blank=True)
    last_error_msg = models.TextField(blank=True)
    tiktok_status_code = models.IntegerField(
        null=True,
        blank=True,
        help_text="statusCode TikTok returned in place of the video data.",
    )

    class Meta:
        indexes = [
            models.Index(
                fields=["status", "-inferred_create_time"],
                name="scrapetarget_queue_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Scrape target for video {self.video_id} [{self.status}]"


class ScrapedDataModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class VideoInfosScraped(ScrapedDataModel):
    """Scraped counterpart of ``research_api.APIVideoInfos``.

    Fields both sources provide carry the same name, type and value format
    as on ``APIVideoInfos``; everything else is scraper-only.
    """

    video = models.ForeignKey(
        "ddcs_metadata.TikTokVideo",
        on_delete=models.CASCADE,
        related_name="scraped_infos",
    )

    # Shared with APIVideoInfos
    description = models.TextField(blank=True)
    create_time = models.DateTimeField(null=True, blank=True)
    duration = models.IntegerField(null=True, blank=True)
    video_mention_list = models.JSONField(null=True, blank=True)
    effect_list = models.JSONField(null=True, blank=True)

    # General information
    location_created = models.CharField(blank=True, max_length=255)
    text_language = models.CharField(blank=True, max_length=255)
    category_type = models.IntegerField(blank=True, null=True)

    original_item = models.BooleanField(blank=True, null=True)
    official_item = models.BooleanField(blank=True, null=True)
    private_item = models.BooleanField(blank=True, null=True)
    is_ad = models.BooleanField(blank=True, null=True)

    # Diversification information
    diversification_labels = models.JSONField(blank=True, null=True)
    diversification_id = models.BigIntegerField(blank=True, null=True)

    # Information on AI use
    is_aigc = models.BooleanField(blank=True, null=True)
    aigc_description = models.TextField(blank=True)

    # File metadata
    height = models.IntegerField(blank=True, null=True)
    width = models.IntegerField(blank=True, null=True)

    # The scraped structure minus URLs and encoding details. TikTok changes
    # its page data without notice; keeping it allows recovering fields we
    # don't map (yet) without scraping again.
    raw = models.JSONField(blank=True, null=True)

    class Meta:
        verbose_name = "Scraped Video Infos"
        verbose_name_plural = "Scraped Video Infos"

    def __str__(self) -> str:
        return f"Scraped metadata for video {self.video}"


class VideoStatisticsScraped(ScrapedDataModel):
    """Scraped counterpart of ``research_api.APIVideoStatistics``."""

    video = models.ForeignKey(
        "ddcs_metadata.TikTokVideo",
        on_delete=models.CASCADE,
        related_name="scraped_statistics",
    )

    # Shared with APIVideoStatistics
    view_count = models.PositiveIntegerField(null=True, blank=True)
    like_count = models.PositiveIntegerField(null=True, blank=True)
    comment_count = models.PositiveIntegerField(null=True, blank=True)
    share_count = models.PositiveIntegerField(null=True, blank=True)
    favorites_count = models.PositiveIntegerField(null=True, blank=True)

    # Scraper only
    repost_count = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "Scraped Video Statistics"
        verbose_name_plural = "Scraped Video Statistics"

    def __str__(self) -> str:
        return f"Scraped statistics for video {self.video}"
