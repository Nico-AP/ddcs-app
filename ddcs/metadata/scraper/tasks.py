import logging
import time

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from redis import Redis

from ddcs.metadata.scraper.models import ScrapeTarget
from ddcs.metadata.scraper.service import (
    ScrapeBatchStats,
    ScraperService,
    clear_cooldown,
    cooldown_until,
    record_last_run,
    register_abort,
)
from ddcs.metadata.utils import recover_db_connection

logger = logging.getLogger(__name__)

_SOFT_TIME_LIMIT = 55 * 60
_TIME_LIMIT = 60 * 60
# Stop starting new videos this long before the soft time limit, so the run
# ends cleanly instead of being interrupted mid-video.
_TIME_BUDGET = _SOFT_TIME_LIMIT - 5 * 60

# Only one scraping run at a time: parallel runs would multiply the request
# rate towards TikTok and work on the same targets.
_SCRAPE_LOCK_KEY = "ddcs:metadata:scraper_lock"

# Pause between a finished run and the one it queues to continue.
_NEXT_RUN_COUNTDOWN = 5


@shared_task(
    acks_late=True,
    soft_time_limit=_SOFT_TIME_LIMIT,
    time_limit=_TIME_LIMIT,
)
def scrape_pending_videos(max_videos: int | None = None) -> ScrapeBatchStats | None:
    """Scrapes queued TikTok videos (see ``ScrapeTarget``) in queue order.

    Does nothing unless ``TIKTOK_SCRAPER_ENABLED`` is set. A run works on at
    most ``max_videos`` (default ``TIKTOK_SCRAPER_BATCH_SIZE``) targets and
    stops early when its time budget is used up or TikTok keeps blocking
    requests.

    Runs follow each other without a gap: a run that leaves pending targets
    behind queues the next one itself. The chain ends when the queue is
    empty or a run was aborted; the scheduled (hourly) run starts it again.

    An aborted run (TikTok appears to be blocking) starts a cool-down
    during which runs are skipped: one hour, doubling with every further
    abort in a row, up to a day. The first healthy run ends it.

    Runs with an explicit ``max_videos`` are one-offs: they queue nothing
    and are not held back by a cool-down.

    Returns the batch statistics, or ``None`` if the run was skipped.
    """
    if not settings.TIKTOK_SCRAPER_ENABLED:
        return None

    paused_until = cooldown_until()
    if paused_until is not None and max_videos is None:
        logger.info(
            "scrape_pending_videos: cooling down until %s; skipping this run.",
            paused_until.isoformat(timespec="minutes"),
        )
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
        paused_until = register_abort()
        logger.error(
            "scrape_pending_videos aborted (%s): TikTok appears to be blocking. "
            "Scraping is paused until %s. Stats: %s",
            stats["abort_reason"],
            paused_until.isoformat(timespec="minutes"),
            stats,
        )
    else:
        logger.info("scrape_pending_videos finished. Stats: %s", stats)
        if stats["scraped"] or stats["unavailable"]:
            # TikTok is serving pages again.
            clear_cooldown()
    record_last_run(stats)

    if _should_continue(stats, max_videos):
        scrape_pending_videos.apply_async(countdown=_NEXT_RUN_COUNTDOWN)
    return stats


def _should_continue(stats: ScrapeBatchStats, max_videos: int | None) -> bool:
    """Whether a finished run should queue the next one right away."""
    if max_videos is not None or stats["aborted"]:
        return False
    # Eager mode (local development) runs the queued task inline, which
    # would recurse through the whole queue.
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        return False
    return ScrapeTarget.objects.filter(status=ScrapeTarget.Status.PENDING).exists()
