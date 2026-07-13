import logging

from celery import shared_task
from ddm.participation.models import Participant

from ddcs.datadonation.services import get_user_data
from ddcs.metadata.services import register_donation_metadata
from ddcs.reports.services import generate_user_report_statistics

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    acks_late=True,
    retry_backoff=30,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
    soft_time_limit=5 * 60,
    time_limit=6 * 60,
)
def process_donation(
    self,  # noqa: ANN001
    participant_pk: int,
) -> None:
    try:
        participant = Participant.objects.get(pk=participant_pk)
    except Participant.DoesNotExist:
        logger.warning(
            "process_donation task exited early: Participant %s does not exist",
            participant_pk,
        )
        return

    try:
        user_data = get_user_data(participant)
        register_donation_metadata(user_data)
        generate_user_report_statistics(participant, user_data)
    except Exception as exc:
        logger.exception("process_donation failed for participant %s", participant_pk)
        raise self.retry(exc=exc) from exc
