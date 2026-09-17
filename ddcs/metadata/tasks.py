import logging
import time
from datetime import date
from typing import Any

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from ddcs.metadata.models import TikTokVideo
from ddcs.metadata.services import ZuseAPIClient
from ddcs.metadata.utils import recover_db_connection

logger = logging.getLogger(__name__)

_SOFT_TIME_LIMIT = 55 * 60
_TIME_LIMIT = 60 * 60


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
    """
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
