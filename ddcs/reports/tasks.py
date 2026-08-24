import logging

from celery import shared_task

from ddcs.reports.metrics.account_metrics import refresh_post_data
from ddcs.reports.plots.public_plot_images import refresh_public_plot_images

logger = logging.getLogger(__name__)


@shared_task(
    acks_late=True,
    soft_time_limit=5 * 60,
    time_limit=6 * 60,
)
def recompute_account_metrics() -> None:
    """Refreshes and caches the data used to render public plots."""
    records = refresh_post_data()
    written = refresh_public_plot_images()
    logger.info(
        "Refreshed public post data cache: %d records; wrote %d plot PNGs.",
        len(records),
        len(written),
    )
