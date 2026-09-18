import logging
import time
from datetime import date, timedelta
from typing import Any

from celery import chain, shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.utils import timezone
from redis import Redis

from ddcs.metadata.models import TikTokVideo
from ddcs.metadata.services import ZuseAPIClient
from ddcs.metadata.utils import recover_db_connection

logger = logging.getLogger(__name__)

_SOFT_TIME_LIMIT = 55 * 60
_TIME_LIMIT = 60 * 60

_BACKFILL_DEFAULT_END_DATE = date(2026, 7, 1)

# Only one classification sync (daily or backfill) may run at a time; a run
# that finds the lock held waits and retries rather than dropping its date.
_SYNC_LOCK_KEY = "ddcs:metadata:classification_sync_lock"
_SYNC_LOCK_BUSY_COUNTDOWN = 60


def _continuation_kwargs(
    target_date: str, max_videos: int | None, processed_count: int
) -> dict[str, Any]:
    """Kwargs for the respawned task continuing this sync.

    ``max_videos`` (if set) is reduced by ``processed_count`` so the total
    videos synced across the whole respawn chain stays capped at the
    original value, rather than resetting on every continuation.
    """
    kwargs: dict[str, Any] = {"target_date": target_date}
    if max_videos is not None:
        kwargs["max_videos"] = max(max_videos - processed_count, 0)
    return kwargs


@shared_task(
    bind=True,
    acks_late=True,
    max_retries=None,
    soft_time_limit=_SOFT_TIME_LIMIT,
    time_limit=_TIME_LIMIT,
)
def sync_tiktok_video_classifications(
    self,  # noqa: ANN001
    target_date: str,
    batch_size: int = 100,
    max_videos: int | None = None,
) -> None:
    """Syncs TikTokVideoClassification from Zuse for videos discovered via
    the Research API on ``target_date`` (ISO format, e.g. "2026-09-09").

    Only considers videos that have an APIVideoInfos row created on that
    date and that don't already have a classification, and syncs them via
    :class:`ZuseAPIClient` in chunks. If ``max_videos`` is given, at most
    that many videos are synced across this call and any continuations it
    respawns.

    A run approaching the soft time limit respawns itself via
    ``self.retry()`` instead of racing to finish, so a single logical sync
    for a busy date can span many task invocations. Because the queryset
    below always excludes already-classified videos, each respawned run is
    naturally idempotent and simply continues where the previous one left
    off — no separate checkpoint/cursor is needed.

    A Redis lock ensures only one classification sync runs at a time across
    all workers. A run that finds the lock held retries after a short delay
    instead of skipping its date.
    """
    lock = Redis.from_url(settings.CELERY_BROKER_URL).lock(
        _SYNC_LOCK_KEY, timeout=_TIME_LIMIT + 60
    )
    if not lock.acquire(blocking=False):
        logger.info(
            "sync_tiktok_video_classifications: lock held; retrying %s in %ds.",
            target_date,
            _SYNC_LOCK_BUSY_COUNTDOWN,
        )
        raise self.retry(countdown=_SYNC_LOCK_BUSY_COUNTDOWN)

    try:
        _sync_classifications(self, target_date, batch_size, max_videos)
    finally:
        try:
            lock.release()
        except Exception:  # noqa: BLE001
            # Lock may have expired between acquire and release; not fatal.
            logger.warning(
                "sync_tiktok_video_classifications: could not release lock cleanly.",
                exc_info=True,
            )


def _sync_classifications(
    self,  # noqa: ANN001
    target_date: str,
    batch_size: int,
    max_videos: int | None,
) -> None:
    """Body of :func:`sync_tiktok_video_classifications`, run under its lock."""
    parsed_date = date.fromisoformat(target_date)

    queryset = (
        TikTokVideo.objects.filter(
            api_infos__created_at__date=parsed_date,
            classifications__isnull=True,
        )
        .distinct()
        .values_list("id_tiktok", flat=True)
    )
    if max_videos is not None:
        queryset = queryset[:max_videos]
    video_ids = list(queryset)
    total = len(video_ids)

    if not video_ids:
        logger.info(
            "No unclassified TikTok videos found for %s.", parsed_date.isoformat()
        )
        return

    logger.info(
        "Syncing %d TikTok video classification(s) for %s (retry #%d).",
        total,
        parsed_date.isoformat(),
        self.request.retries,
    )

    client = ZuseAPIClient()
    start = time.monotonic()

    # Stop starting new chunks this long before the soft time limit, leaving
    # room to respawn cleanly instead of hitting SoftTimeLimitExceeded.
    time_budget_seconds = _SOFT_TIME_LIMIT - (
        batch_size * ZuseAPIClient.REQUEST_TIMEOUT_SECONDS
    )

    for i in range(0, total, batch_size):
        chunk = video_ids[i : i + batch_size]
        try:
            client.sync_videos(chunk)
        except SoftTimeLimitExceeded:
            logger.warning(
                "sync_tiktok_video_classifications hit the soft time limit "
                "mid-chunk for %s (%d/%d done); respawning to continue.",
                parsed_date.isoformat(),
                i,
                total,
            )
            recover_db_connection()
            raise self.retry(
                kwargs=_continuation_kwargs(target_date, max_videos, i),
                countdown=5,
            ) from None

        processed = i + len(chunk)
        if processed < total and time.monotonic() - start > time_budget_seconds:
            logger.info(
                "sync_tiktok_video_classifications approaching the soft time "
                "limit for %s (%d/%d done); respawning to continue.",
                parsed_date.isoformat(),
                processed,
                total,
            )
            raise self.retry(
                kwargs=_continuation_kwargs(target_date, max_videos, processed),
                countdown=5,
            )

    logger.info(
        "Finished syncing TikTok video classification(s) for %s.",
        parsed_date.isoformat(),
    )


@shared_task
def notify_backfill_chain_broken(
    request: Any,  # noqa: ANN401
    exc: BaseException,
    traceback: str,
    end_date: str,
) -> None:
    """Error callback of the backfill chain: logs an error, which the
    ``mail_admins`` log handler turns into an email to the admins.

    Celery calls it with the failed task's ``request``, the exception and the
    traceback when a sync task in the chain fails for good (retries don't
    count). ``request.chain`` holds the dates that will now not run.
    """
    failed_date = request.kwargs["target_date"]
    skipped_dates = [sig["kwargs"]["target_date"] for sig in request.chain or []]
    logger.error(
        "TikTok classification backfill chain broke at %s (%r). %d later "
        "date(s) were not started: %s. Resume with "
        "backfill_tiktok_video_classifications(start_date=%r, end_date=%r).",
        failed_date,
        exc,
        len(skipped_dates),
        ", ".join(reversed(skipped_dates)) or "none",
        failed_date,
        end_date,
    )


@shared_task
def backfill_tiktok_video_classifications(
    start_date: str | None = None,
    end_date: str | None = None,
    batch_size: int = 100,
    max_videos: int | None = None,
) -> int:
    """Kicks off :func:`sync_tiktok_video_classifications` for every date from
    ``start_date`` back to ``end_date`` (both inclusive, ISO format).

    ``start_date`` is the newest date and defaults to today; ``end_date`` is
    the oldest date and defaults to 2026-07-01.

    The sync tasks are queued as a Celery chain, newest date first, so only
    one date is queued (and running) at a time and the next starts once the
    previous one, including any of its time-limit respawns, has finished.
    If a date's sync fails outright, the chain stops there and
    :func:`notify_backfill_chain_broken` logs an error (which emails the
    admins) naming the failed date and how to resume; re-running the
    backfill from that date is safe since already-classified videos are
    skipped. ``batch_size`` and ``max_videos`` are passed through
    to every sync task (``max_videos`` therefore caps each date separately).

    Returns the number of sync tasks queued.
    """
    newest = date.fromisoformat(start_date) if start_date else timezone.localdate()
    oldest = date.fromisoformat(end_date) if end_date else _BACKFILL_DEFAULT_END_DATE
    if newest < oldest:
        msg = (
            f"start_date ({newest.isoformat()}) must not be earlier than "
            f"end_date ({oldest.isoformat()})."
        )
        raise ValueError(msg)

    total = (newest - oldest).days + 1
    logger.info(
        "Backfilling TikTok video classifications for %d date(s), %s down to %s.",
        total,
        newest.isoformat(),
        oldest.isoformat(),
    )

    chain(
        *(
            sync_tiktok_video_classifications.si(
                target_date=(newest - timedelta(days=offset)).isoformat(),
                batch_size=batch_size,
                max_videos=max_videos,
            )
            for offset in range(total)
        )
    ).on_error(
        notify_backfill_chain_broken.s(end_date=oldest.isoformat())
    ).apply_async()

    return total
