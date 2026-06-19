import logging
from datetime import datetime, timedelta

from celery import shared_task
from django.utils import timezone

from ddcs.metadata.models import TikTokHashtag, TikTokUser
from ddcs.metadata.research_api.service import ResearchAPIService

logger = logging.getLogger(__name__)


@shared_task
def query_videos_by_user(
    batch_size: int = 50,
    query_start_date: datetime | None = None,
    query_end_date: datetime | None = None,
) -> None:
    """Query videos published by selected users through Research API.

    Args:
        batch_size: Number of users to query at a time. Defaults to 50.
        query_start_date: Start date for querying videos.
            Defaults to 4 days before today.
        query_end_date: End date for querying videos.
            Defaults to 4 days before today.

    Returns:
        None
    """
    logger.info("Starting query_videos_by_user task.")

    users_to_query = (
        TikTokUser.objects.order_by(
            "-monitoring_priority_api",
            "api_last_monitored_at",
        )
        .filter(monitor_api=True)
        .exclude(api_last_monitored_at__date=timezone.now().date())
    )
    if not users_to_query.exists():
        logger.info("No users registered for monitoring (query_videos_by_user).")
        return

    service = ResearchAPIService()

    if not query_end_date:
        query_end_date = timezone.now() - timedelta(days=4)
    if not query_start_date:
        query_start_date = query_end_date

    usernames = list(users_to_query.values_list("name", flat=True))
    for i in range(0, len(usernames), batch_size):
        user_batch = usernames[i : i + batch_size]
        service.get_user_videos(
            user_batch,
            end_date=query_end_date.date(),
            start_date=query_start_date.date(),
        )

        # Update monitoring status
        TikTokUser.objects.filter(name__in=user_batch).update(
            api_last_monitored_at=timezone.now(),
        )

    logger.info(
        "query_videos_by_user: Completed sync. "
        "Total videos retrieved: %d. "
        "Created %d users, %d videos, %d hashtags, %d music entries. "
        "Parameters: {batch_size: %d, query_end_date: %s, query_start_date: %s}",
        service.sync_stats["videos_retrieved"],
        service.sync_stats["users_created"],
        service.sync_stats["videos_created"],
        service.sync_stats["hashtags_created"],
        service.sync_stats["music_created"],
        batch_size,
        query_end_date,
        query_start_date,
    )


@shared_task
def query_videos_by_hashtag(batch_size: int = 50) -> None:
    """Query videos by selected hashtags through Research API.

    Args:
        batch_size: Number of hashtags to query at a time. Defaults to 50.

    Returns:
        None
    """
    logger.info("Starting query_videos_by_hashtag task.")

    hashtags_to_query = (
        TikTokHashtag.objects.order_by(
            "-monitoring_priority_api",
            "api_last_monitored_at",
        )
        .filter(monitor_api=True)
        .exclude(api_last_monitored_at__date=timezone.now().date())
    )
    if not hashtags_to_query.exists():
        logger.info("No hashtags registered for monitoring (query_videos_by_hashtag).")
        return

    service = ResearchAPIService()
    query_end_date = timezone.now() - timedelta(days=1)
    query_start_date = query_end_date - timedelta(days=3)

    hashtags = list(hashtags_to_query.values_list("name", flat=True))
    for i in range(0, len(hashtags), batch_size):
        hashtag_batch = hashtags[i : i + batch_size]
        service.get_hashtag_videos(
            hashtag_batch,
            end_date=query_end_date.date(),
            start_date=query_start_date.date(),
        )

        # Update monitoring status
        TikTokUser.objects.filter(name__in=hashtag_batch).update(
            api_last_monitored_at=timezone.now(),
        )

    logger.info(
        "query_videos_by_hashtag: Completed sync. "
        "Total videos retrieved: %d. "
        "Created %d users, %d videos, %d hashtags, %d music entries. "
        "Parameters: {batch_size: %d, query_end_date: %s, query_start_date: %s}",
        service.sync_stats["videos_retrieved"],
        service.sync_stats["users_created"],
        service.sync_stats["videos_created"],
        service.sync_stats["hashtags_created"],
        service.sync_stats["music_created"],
        batch_size,
        query_end_date,
        query_start_date,
    )
