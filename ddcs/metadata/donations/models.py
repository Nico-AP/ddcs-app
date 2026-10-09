from django.db import models


class DonationVideoInfos(models.Model):
    """Donation counterpart of ``research_api.APIVideoInfos``: what the
    donations tell about a video.

    One row per video that at least one donation shows as watched, liked or
    bookmarked. Donations are stored encrypted, so whether (and when) donors
    interacted with a video cannot be queried from them; this table keeps
    that fact. The prioritised video API derives its priorities from it.
    Rows are written through
    :func:`ddcs.metadata.donations.service.record_donated_videos` only.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    video = models.OneToOneField(
        "ddcs_metadata.TikTokVideo",
        on_delete=models.CASCADE,
        related_name="donation_infos",
    )

    # Number of donations per kind of interaction. A donor who watched the
    # video several times counts once. Not exact: see ``record_donated_videos``.
    watched_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of donations whose watch history contains the video.",
    )
    liked_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of donations whose liked videos contain the video.",
    )
    bookmarked_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of donations whose bookmarked videos contain the video.",
    )

    last_interaction_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Most recent view, like or bookmark of the video across all "
        "donations.",
    )
    last_interaction_in_window_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Most recent view, like or bookmark of the video within the "
        "watch window.",
    )

    class Meta:
        verbose_name = "Donation Video Infos"
        verbose_name_plural = "Donation Video Infos"

    def __str__(self) -> str:
        return f"Donation infos for video {self.video_id}"
