from django.db import models


class ScrapedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Scraping information
    last_scraped_at = models.DateTimeField(blank=True, null=True)
    scraping_success = models.BooleanField(default=False)
    scraping_priority = models.IntegerField(default=0)
    scraping_error_msg = models.TextField(blank=True)

    class Meta:
        abstract = True


class VideoInfosScraped(ScrapedModel):
    video = models.ForeignKey("ddcs.metadata.TikTokVideo", on_delete=models.CASCADE)

    # General information
    description = models.TextField(blank=True)
    create_time = models.DateTimeField(blank=True, null=True)
    # optional: inferred create time
    location_created = models.CharField(blank=True, max_length=255)

    original_item = models.BooleanField(blank=True, null=True)
    official_item = models.BooleanField(blank=True, null=True)

    # Diversification information
    diversification_labels = None  # TODO
    diversification_id = models.BigIntegerField(blank=True, null=True)

    channel_tags = None  # TODO: Why is this here?

    # Information on AI use
    is_aigc = models.BooleanField(blank=True, null=True)
    aigc_lable_type = None  # TODO
    aigc_description = models.TextField(blank=True)  # TODO: Maybe CharField?

    # File metadata
    duration = models.FloatField(
        blank=True, null=True
    )  # TODO: Check if Integer or Float
    height = models.IntegerField(blank=True, null=True)
    width = models.IntegerField(blank=True, null=True)

    # Audio and transcription
    has_original_audio = models.BooleanField(blank=True, null=True)
    enable_audio_caption = models.BooleanField(blank=True, null=True)
    no_caption_reason = models.IntegerField(
        blank=True, null=True
    )  # TODO: Is this really int?

    # Music
    # TODO: Is this reliably pointing to a foreign key or should we store on video?

    def __str__(self) -> str:
        return f"Scraped metadata for TikTok video {self.video.id}"


class UserInfosScraped(ScrapedModel):
    user = models.ForeignKey("ddcs.metadata.TikTokUser", on_delete=models.CASCADE)

    create_time = models.DateTimeField(blank=True, null=True)

    username = models.CharField(blank=True, max_length=255)
    nickname = models.CharField(blank=True, max_length=255)
    signature = models.TextField(blank=True)
    private_account = models.BooleanField(blank=True, null=True)

    verified = models.BooleanField(blank=True, null=True)
    ftc = models.BooleanField(blank=True, null=True)

    relation = models.IntegerField(blank=True, null=True)  # TODO: What is this?
    open_favorite = models.BooleanField(blank=True, null=True)
    comment_setting = models.BooleanField(blank=True, null=True)
    duet_setting = models.IntegerField(blank=True, null=True)
    stitch_setting = models.IntegerField(blank=True, null=True)

    secret = models.BooleanField(blank=True, null=True)
    is_ad_virtual = models.BooleanField(blank=True, null=True)
    download_setting = models.IntegerField(blank=True, null=True)

    recommend_reason = models.CharField(blank=True, max_length=255)
    suggest_account_bind = models.BooleanField(blank=True, null=True)

    def __str__(self) -> str:
        return f"Scraped metadata for TikTok user {self.user.id}"
