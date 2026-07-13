from ddm.participation.models import Participant
from django.db import models


class ParticipantReportStatistics(models.Model):
    participant = models.OneToOneField(Participant, on_delete=models.CASCADE)
    generated_at = models.DateTimeField(auto_now_add=True)

    videos_seen_count_total = models.IntegerField(default=0)

    seen_pol_video_ids = models.JSONField()
    liked_pol_video_ids = models.JSONField()
    followed_pol_users = models.JSONField()

    party_counts = models.JSONField()
    daily_party_counts = models.JSONField()
    hashtags_by_pol_video = models.JSONField()
    top_videos = models.JSONField(default=list)

    party_hashtags = models.JSONField()
    non_party_hashtags = models.JSONField()

    behaviour_comparisons = models.JSONField(default=list)

    class Meta:
        ordering = ("-generated_at",)

    def __str__(self) -> str:
        return f"Report statistics for {self.participant.external_id}"
