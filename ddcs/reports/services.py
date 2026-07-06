from ddm.participation.models import Participant

from ddcs.core.types import (
    TikTokUserData,
)
from ddcs.reports.metrics.user_metrics import compute_user_report_metrics
from ddcs.reports.models import ParticipantReportStatistics


def generate_user_report_statistics(
    participant: Participant, data: TikTokUserData
) -> ParticipantReportStatistics:
    statistics = compute_user_report_metrics(data)

    return ParticipantReportStatistics.objects.create(
        participant=participant, **statistics
    )
