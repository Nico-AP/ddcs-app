import logging
from datetime import date

from celery import shared_task

from ddcs.metadata.models import TikTokVideo
from ddcs.metadata.services import ZuseAPIClient

logger = logging.getLogger(__name__)


@shared_task(acks_late=True, soft_time_limit=55 * 60, time_limit=60 * 60)
def sync_tiktok_video_classifications(
    target_date: str, max_videos: int | None = None
) -> None:
    """Syncs TikTokVideoClassification from Zuse for videos discovered via
    the Research API on ``target_date`` (ISO format, e.g. "2026-09-09").

    Only considers videos that have an APIVideoInfos row created on that
    date and that don't already have a classification, and syncs them via
    :class:`ZuseAPIClient` in batches of ``ZuseAPIClient.BATCH_SIZE``. If
    ``max_videos`` is given, at most that many videos are synced.
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

    if not video_ids:
        logger.info(
            "No unclassified TikTok videos found for %s.", parsed_date.isoformat()
        )
        return

    logger.info(
        "Syncing %d TikTok video classification(s) for %s.",
        len(video_ids),
        parsed_date.isoformat(),
    )

    client = ZuseAPIClient()
    batch_size = ZuseAPIClient.BATCH_SIZE
    for i in range(0, len(video_ids), batch_size):
        client.sync_videos(video_ids[i : i + batch_size])
