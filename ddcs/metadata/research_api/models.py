from django.db import models


class ResearchAPIDataModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class APIVideoInfos(ResearchAPIDataModel):
    video = models.ForeignKey(
        "ddcs_metadata.TikTokVideo",
        on_delete=models.CASCADE,
        related_name="api_infos",
    )

    # Infos retrieved from API:
    description = models.TextField(blank=True)
    create_time = models.DateTimeField(null=True, blank=True)
    region_code = models.CharField(max_length=255, blank=True)
    duration = models.IntegerField(null=True, blank=True)
    voice_to_text = models.TextField(blank=True)
    is_stem_verified = models.BooleanField(null=True, blank=True)
    video_mention_list = models.JSONField(null=True, blank=True)
    video_label = models.JSONField(null=True, blank=True)
    effect_list = models.JSONField(null=True, blank=True)

    class Meta:
        verbose_name = "API Video Infos"
        verbose_name_plural = "API Video Infos"

    def __str__(self) -> str:
        return f"Research API video infos for video {self.video}"


class APIVideoStatistics(ResearchAPIDataModel):
    video = models.ForeignKey(
        "ddcs_metadata.TikTokVideo",
        on_delete=models.CASCADE,
        related_name="statistics",
    )

    view_count = models.PositiveIntegerField(null=True, blank=True)
    like_count = models.PositiveIntegerField(null=True, blank=True)
    comment_count = models.PositiveIntegerField(null=True, blank=True)
    share_count = models.PositiveIntegerField(null=True, blank=True)
    favorites_count = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "API Video Statistics"
        verbose_name_plural = "API Video Statistics"

    def __str__(self) -> str:
        return f"Research API statistics for video {self.video}"


class APIUserInfos(ResearchAPIDataModel):
    user = models.ForeignKey(
        "ddcs_metadata.TikTokUser",
        on_delete=models.CASCADE,
        related_name="api_infos",
    )

    # Infos retrieved from API:
    name = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255, blank=True)
    is_verified = models.BooleanField(null=True, blank=True)
    is_private = models.BooleanField(null=True, blank=True)

    class Meta:
        verbose_name = "API User Infos"
        verbose_name_plural = "API User Infos"

    def __str__(self) -> str:
        return f"Research API metadata for user {self.user}"


class APIUserStatistics(ResearchAPIDataModel):
    user = models.ForeignKey(
        "ddcs_metadata.TikTokUser",
        on_delete=models.CASCADE,
        related_name="statistics",
    )

    following_count = models.PositiveIntegerField(null=True, blank=True)
    follower_count = models.PositiveIntegerField(null=True, blank=True)
    video_count = models.PositiveIntegerField(null=True, blank=True)
    likes_count = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "API User Statistics"
        verbose_name_plural = "API User Statistics"

    def __str__(self) -> str:
        return f"Research API statistics for user {self.user}"


class APIMusicInfos(ResearchAPIDataModel):
    music = models.ForeignKey(
        "ddcs_metadata.TikTokMusic",
        on_delete=models.CASCADE,
        related_name="api_infos",
    )

    # Infos retrieved from API:
    name = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "API Music Infos"
        verbose_name_plural = "API Music Infos"

    def __str__(self) -> str:
        return f"Research API metadata for TikTok Music {self.music}"


class APIHashtagInfos(ResearchAPIDataModel):
    hashtag = models.ForeignKey(
        "ddcs_metadata.TikTokHashtag",
        on_delete=models.CASCADE,
        related_name="api_infos",
    )

    # Infos retrieved from API:
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = "API Hashtag Infos"
        verbose_name_plural = "API Hashtag Infos"

    def __str__(self) -> str:
        return f"Research API metadata for TikTok Hashtag {self.hashtag}"
