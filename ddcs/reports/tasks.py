import logging

from celery import shared_task

from ddcs.reports.metrics.account_metrics import refresh_post_data

logger = logging.getLogger(__name__)


@shared_task(
    acks_late=True,
    soft_time_limit=5 * 60,
    time_limit=6 * 60,
)
def recompute_account_metrics() -> None:
    """Refreshes and caches the data used to render public plots."""
    records = refresh_post_data()
    logger.info("Refreshed public post data cache: %d records.", len(records))
