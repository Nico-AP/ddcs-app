import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.utils import timezone

from ddcs.metadata.models import ResearchAPIQueryTracker, TikTokHashtag, TikTokUser
from ddcs.metadata.research_api.service import ResearchAPIService

logger = logging.getLogger(__name__)


# TODO: Add appropriate autoretry_for=(ResearchAPIError, requests.RequestException)
@shared_task(
    bind=True,
    acks_late=True,
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
    soft_time_limit=55 * 60,
    time_limit=60 * 60,
)
def query_videos_by_user(
    self,  # noqa: ANN001
    batch_size: int = 50,
    query_start_date: str | None = None,
    query_end_date: str | None = None,
) -> None:
    """Query videos published by selected users through Research API.

    Args:
        batch_size: Number of users to query at a time. Defaults to 50.
        query_start_date: Start date for querying videos as a string in the
            format "20201231" ("%Y%m%d"). Defaults to 4 days before today.
        query_end_date: End date for querying videos as a string in the
            format "20201231" ("%Y%m%d"). Defaults to 4 days before today.

    Returns:
        None
    """
    logger.info("Starting query_videos_by_user task.")

    usernames = list(
        TikTokUser.objects.filter(monitor_api=True)
        .exclude(api_last_monitored_at__date=timezone.now().date())
        .order_by("-monitoring_priority_api", "api_last_monitored_at")
        .values_list("name", flat=True)
    )

    if not usernames:
        logger.info("No users registered for monitoring (query_videos_by_user).")
        return

    if query_end_date:
        query_end_date = datetime.strptime(query_end_date, "%Y%m%d").replace(tzinfo=UTC)
    else:
        query_end_date = timezone.now() - timedelta(days=4)

    if query_start_date:
        query_start_date = datetime.strptime(query_start_date, "%Y%m%d").replace(
            tzinfo=UTC
        )
    else:
        query_start_date = query_end_date

    query_parameter = {
        "start": str(query_start_date),
        "end": str(query_end_date),
        "batch_size": batch_size,
        "queried_objects": usernames,
    }
    tracker = register_query_tracker("query_videos_by_user", query_parameter)

    service = ResearchAPIService()
    total_batches = (len(usernames) + batch_size - 1) // batch_size
    processed_batches = 0
    try:
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

            processed_batches += 1
            logger.info(
                "query_videos_by_user: batch %d/%d done (%d users). "
                "Cumulative videos: %d.",
                processed_batches,
                total_batches,
                len(user_batch),
                service.sync_stats["videos_retrieved"],
            )

    except SoftTimeLimitExceeded:
        logger.warning(
            "query_videos_by_user hit soft time limit after %d/%d batches; "
            "remaining hashtags will be picked up on the next run.",
            processed_batches,
            total_batches,
        )
        update_query_tracker(
            tracker,
            service.sync_stats,
            ResearchAPIQueryTracker.Status.SOFT_TIME_LIMIT_EXCEEDED,
        )
        return

    except Exception:
        logger.exception(
            "query_videos_by_user failed after %d/%d batches.",
            processed_batches,
            total_batches,
        )
        update_query_tracker(
            tracker, service.sync_stats, ResearchAPIQueryTracker.Status.FAILED
        )
        raise

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
    update_query_tracker(
        tracker, service.sync_stats, ResearchAPIQueryTracker.Status.COMPLETED
    )


# TODO: Add appropriate autoretry_for=(ResearchAPIError, requests.RequestException)
@shared_task(
    bind=True,
    acks_late=True,
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
    soft_time_limit=55 * 60,
    time_limit=60 * 60,
)
def query_videos_by_hashtag(
    self,  # noqa: ANN001
    batch_size: int = 50,
    query_start_date: str | None = None,
    query_end_date: str | None = None,
) -> None:
    """Query videos by selected hashtags through Research API.

    Args:
        batch_size: Number of hashtags to query at a time. Defaults to 50.
        query_start_date: Start date for querying videos as a string in the
            format "20201231" ("%Y%m%d"). Defaults to 4 days before today.
        query_end_date: End date for querying videos as a string in the
            format "20201231" ("%Y%m%d"). Defaults to 4 days before today.

    Returns:
        None
    """
    logger.info("Starting query_videos_by_hashtag task.")

    hashtags = list(
        TikTokHashtag.objects.filter(monitor_api=True)
        .exclude(api_last_monitored_at__date=timezone.now().date())
        .order_by("-monitoring_priority_api", "api_last_monitored_at")
        .values_list("name", flat=True)
    )
    if not hashtags:
        logger.info("No hashtags registered for monitoring (query_videos_by_hashtag).")
        return

    if query_end_date:
        query_end_date = datetime.strptime(query_end_date, "%Y%m%d").replace(tzinfo=UTC)
    else:
        query_end_date = timezone.now() - timedelta(days=4)

    if query_start_date:
        query_start_date = datetime.strptime(query_start_date, "%Y%m%d").replace(
            tzinfo=UTC
        )
    else:
        query_start_date = query_end_date

    query_parameter = {
        "start": str(query_start_date),
        "end": str(query_end_date),
        "batch_size": batch_size,
        "queried_objects": hashtags,
    }
    tracker = register_query_tracker(
        "query_videos_by_hashtag",
        query_parameter,
    )

    service = ResearchAPIService()
    total_batches = (len(hashtags) + batch_size - 1) // batch_size
    processed_batches = 0
    try:
        for i in range(0, len(hashtags), batch_size):
            hashtag_batch = hashtags[i : i + batch_size]
            service.get_hashtag_videos(
                hashtag_batch,
                end_date=query_end_date.date(),
                start_date=query_start_date.date(),
            )

            # Update monitoring status
            TikTokHashtag.objects.filter(name__in=hashtag_batch).update(
                api_last_monitored_at=timezone.now(),
            )

            processed_batches += 1
            logger.info(
                "query_videos_by_hashtag: batch %d/%d done (%d hashtags). "
                "Cumulative videos: %d.",
                processed_batches,
                total_batches,
                len(hashtag_batch),
                service.sync_stats["videos_retrieved"],
            )

    except SoftTimeLimitExceeded:
        logger.warning(
            "query_videos_by_hashtag hit soft time limit after %d/%d batches; "
            "remaining hashtags will be picked up on the next run.",
            processed_batches,
            total_batches,
        )
        update_query_tracker(
            tracker,
            service.sync_stats,
            ResearchAPIQueryTracker.Status.SOFT_TIME_LIMIT_EXCEEDED,
        )
        return

    except Exception:
        logger.exception(
            "query_videos_by_hashtag failed after %d/%d batches.",
            processed_batches,
            total_batches,
        )
        update_query_tracker(
            tracker, service.sync_stats, ResearchAPIQueryTracker.Status.FAILED
        )
        raise

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
    update_query_tracker(
        tracker, service.sync_stats, ResearchAPIQueryTracker.Status.COMPLETED
    )


def register_query_tracker(
    query_function: str,
    query_parameter: dict[str, Any],
) -> ResearchAPIQueryTracker:
    return ResearchAPIQueryTracker.objects.create(
        start_time=timezone.now(),
        query_function=query_function,
        query_parameters=query_parameter,
    )


def update_query_tracker(
    query_tracker: ResearchAPIQueryTracker,
    sync_stats: dict[str, Any],
    query_status: str,
) -> None:
    query_tracker.end_time = timezone.now()
    query_tracker.query_status = query_status
    query_tracker.query_result = sync_stats
    query_tracker.save()
