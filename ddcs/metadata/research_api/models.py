from django.db import models


class ResearchAPIDataModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class VideoInfosAPI(ResearchAPIDataModel):
    video = models.ForeignKey("ddcs.metadata.TikTokVideo", on_delete=models.CASCADE)

    description = models.TextField(
        blank=True,
        help_text="Video description as retrieved from TikTok.",
    )
    create_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Video creation time as retrieved from TikTok.",
    )
    inferred_create_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Create time as inferred from the TikTok ID.",
    )
    location_created = models.CharField(
        max_length=255,
        blank=True,
        help_text=(
            "Country code where the video was created as retrieved from TikTok."
        ),
    )
    duration = models.IntegerField(
        null=True,
        blank=True,
        help_text="Video duration as retrieved from TikTok.",
    )

    # TODO: Add music, effects, hashtags as many2many fields

    def __str__(self) -> str:
        return f"Research API metadata for TikTok video {self.video.id}"


class UserInfosAPI(ResearchAPIDataModel):
    user = models.ForeignKey("ddcs.metadata.TikTokUser", on_delete=models.CASCADE)

    name = models.CharField(
        max_length=255,
        help_text="Unique name of the creator.",
        unique=True,
    )

    display_name = models.CharField(
        max_length=255,
        help_text="Longer name of the creator.",
        blank=True,
    )

    is_verified = models.BooleanField(
        null=True,
        blank=True,
        help_text="Whether a creator is verified or not.",
    )

    is_private = models.BooleanField(
        null=True,
        blank=True,
        help_text="Whether a creator is private or not.",
    )

    def __str__(self) -> str:
        return f"Research API metadata for TikTok user {self.user.id}"
