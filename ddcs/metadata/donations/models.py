from django.db import models


class DonationVideoInfos(models.Model):
    """Donation counterpart of ``research_api.APIVideoInfos``: what the
    donations tell about a video.

    One row per video that occurs in the watch history of at least one
    donation. Donations are stored encrypted, so whether (and when) donors
    saw a video cannot be queried from them; this table keeps that fact. The
    prioritised video API derives its priorities from it. Rows are written
    through :func:`ddcs.metadata.donations.service.record_donated_videos`
    only.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    video = models.OneToOneField(
        "ddcs_metadata.TikTokVideo",
        on_delete=models.CASCADE,
        related_name="donation_infos",
    )

    last_seen_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Most recent view of the video across all donations.",
    )
    last_seen_in_window_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Most recent view of the video within the watch window.",
    )

    class Meta:
        verbose_name = "Donation Video Infos"
        verbose_name_plural = "Donation Video Infos"

    def __str__(self) -> str:
        return f"Donation infos for video {self.video_id}"
