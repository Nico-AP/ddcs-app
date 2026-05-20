from django.db import models


class TikTokVideo(models.Model):
    video_id = models.BigIntegerField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "TikTok Video"
        verbose_name_plural = "TikTok Videos"

    def __str__(self) -> str:
        return f"TikTok Video {self.pk}"


class TikTokUser(models.Model):
    user_id = models.BigIntegerField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Monitoring settings
    monitor = models.BooleanField(default=False)
    monitoring_priority = models.IntegerField(default=0)
    last_monitored_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        verbose_name = "TikTok User"
        verbose_name_plural = "TikTok Users"

    def __str__(self) -> str:
        return f"TikTok User {self.pk}"


# TODO: Add Music, Effects, Hashtags if applicable.
