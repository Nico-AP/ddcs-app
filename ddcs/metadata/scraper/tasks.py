import logging
import time

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from redis import Redis

from ddcs.metadata.utils import recover_db_connection

from .service import ScrapeBatchStats, ScraperService

logger = logging.getLogger(__name__)

_SOFT_TIME_LIMIT = 55 * 60
_TIME_LIMIT = 60 * 60
# Stop starting new videos this long before the soft time limit, so the run
# ends cleanly instead of being interrupted mid-video.
_TIME_BUDGET = _SOFT_TIME_LIMIT - 5 * 60

# Only one scraping run at a time: parallel runs would multiply the request
# rate towards TikTok and work on the same targets.
_SCRAPE_LOCK_KEY = "ddcs:metadata:scraper_lock"


@shared_task(
    acks_late=True,
    soft_time_limit=_SOFT_TIME_LIMIT,
    time_limit=_TIME_LIMIT,
)
def scrape_pending_videos(max_videos: int | None = None) -> ScrapeBatchStats | None:
    """Scrapes queued TikTok videos (see ``ScrapeTarget``), newest first.

    Does nothing unless ``TIKTOK_SCRAPER_ENABLED`` is set. A run works on at
    most ``max_videos`` (default ``TIKTOK_SCRAPER_BATCH_SIZE``) targets and
    stops early when its time budget is used up or TikTok keeps blocking
    requests; whatever is left stays queued for the next scheduled run.

    Returns the batch statistics, or ``None`` if the run was skipped.
    """
    if not settings.TIKTOK_SCRAPER_ENABLED:
        return None

    lock = Redis.from_url(settings.CELERY_BROKER_URL).lock(
        _SCRAPE_LOCK_KEY, timeout=_TIME_LIMIT + 60
    )
    if not lock.acquire(blocking=False):
        logger.info("scrape_pending_videos: lock held; skipping this run.")
        return None

    try:
        stats = ScraperService().scrape_batch(
            limit=max_videos or settings.TIKTOK_SCRAPER_BATCH_SIZE,
            deadline=time.monotonic() + _TIME_BUDGET,
        )
    except SoftTimeLimitExceeded:
        recover_db_connection()
        logger.warning("scrape_pending_videos hit the soft time limit.")
        return None
    finally:
        try:
            lock.release()
        except Exception:  # noqa: BLE001
            # Lock may have expired between acquire and release; not fatal.
            logger.warning(
                "scrape_pending_videos: could not release lock cleanly.",
                exc_info=True,
            )

    if stats["aborted"]:
        logger.error(
            "scrape_pending_videos aborted: TikTok blocked %d requests in a row. "
            "Stats: %s",
            ScraperService.CONSECUTIVE_BLOCKS_BEFORE_ABORT,
            stats,
        )
    else:
        logger.info("scrape_pending_videos finished. Stats: %s", stats)
    return stats
