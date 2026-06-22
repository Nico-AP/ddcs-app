import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.db.models import QuerySet
from django.utils import timezone

from ddcs.metadata.models import ResearchAPIQueryTracker, TikTokHashtag, TikTokUser
from ddcs.metadata.research_api.service import ResearchAPIService

logger = logging.getLogger(__name__)


def _run_query_task(  # noqa: PLR0913
    task_name: str,
    queryset: QuerySet,
    service_method_name: str,
    batch_size: int,
    query_start_date: str | None,
    query_end_date: str | None,
    update_model: TikTokHashtag | TikTokUser,
    filter_field_name: str = "name",
) -> None:
    """Shared logic for querying TikTok videos via the Research API.

    Fetches all items (users or hashtags) that are flagged for monitoring but
    have not yet been queried today, then queries the Research API for their
    videos in batches.

    After each successful batch, the items in that batch are marked as monitored
    so they won't be picked up again on the next run. If a batch fails, the error
    is recorded and the task moves on to the next batch.

    Once all batches are processed, the overall result is saved as one of:
    - COMPLETED: all batches succeeded.
    - PARTIAL_FAILURE: at least one batch failed, with details of which batches
      and why stored for later inspection.
    - SOFT_TIME_LIMIT_EXCEEDED: the worker ran out of time mid-run; any remaining
      items will be picked up on the next scheduled run.

    Args:
        task_name: Human-readable name used in logs and the query tracker.
        queryset: Pre-filtered queryset of items to monitor
            (e.g. TikTokUser or TikTokHashtag).
        service_method_name: Name of the ResearchAPIService method to call per batch.
        batch_size: Number of items to include in each API request.
        query_start_date: Start of the video date range as "YYYYMMDD".
            Defaults to 4 days ago.
        query_end_date: End of the video date range as "YYYYMMDD".
            Defaults to 4 days ago.
        update_model: The Django model to update after each successful batch.
        filter_field_name: The field name used to filter and identify items.
            Defaults to "name".

    Note:
        For the actual tasks, see `query_videos_by_user` and `query_videos_by_hashtag`
        below.
    """
    logger.info("Starting %s task.", task_name)

    items = list(
        queryset.exclude(api_last_monitored_at__date=timezone.now().date())
        .order_by("-monitoring_priority_api", "api_last_monitored_at")
        .values_list(filter_field_name, flat=True)
    )

    if not items:
        logger.info("No items registered for monitoring (%s).", task_name)
        return

    if query_end_date:
        query_end_date = datetime.strptime(query_end_date, "%Y%m%d").replace(tzinfo=UTC)
    else:
        query_end_date = timezone.now() - timedelta(days=4)

    query_start_date = (
        datetime.strptime(query_start_date, "%Y%m%d").replace(tzinfo=UTC)
        if query_start_date
        else query_end_date
    )

    tracker = register_query_tracker(
        task_name,
        {
            "start": str(query_start_date),
            "end": str(query_end_date),
            "batch_size": batch_size,
            "queried_objects": items,
        },
    )

    service = ResearchAPIService()
    service_method = getattr(service, service_method_name)
    total_batches = (len(items) + batch_size - 1) // batch_size
    processed_batches = 0
    failed_batches = []

    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        try:
            service_method(
                batch,
                end_date=query_end_date.date(),
                start_date=query_start_date.date(),
            )

            update_model.objects.filter(**{f"{filter_field_name}__in": batch}).update(
                api_last_monitored_at=timezone.now()
            )

            processed_batches += 1
            logger.info(
                "%s: batch %d/%d done (%d items). Cumulative videos: %d.",
                task_name,
                processed_batches,
                total_batches,
                len(batch),
                service.sync_stats["videos_retrieved"],
            )

        except SoftTimeLimitExceeded:
            logger.warning(
                "%s hit soft time limit after %d/%d batches; "
                "remaining items will be picked up on the next run.",
                task_name,
                processed_batches,
                total_batches,
            )
            update_query_tracker(
                tracker,
                service.sync_stats,
                ResearchAPIQueryTracker.Status.SOFT_TIME_LIMIT_EXCEEDED,
            )
            return

        # TODO: Handle query limit exceeded explicitly.

        except Exception as exc:
            msg = (
                f"{task_name} failed after {processed_batches}/{total_batches} batches "
                f"with {type(exc).__name__}: {exc}. Failed batch: {batch or 'unknown'}."
            )

            logger.exception(msg)
            update_query_tracker(
                tracker,
                service.sync_stats,
                ResearchAPIQueryTracker.Status.FAILED,
                exception_details={"exception details": msg},
            )

    if failed_batches:
        logger.warning(
            "%s completed with %d/%d failed batches.",
            task_name,
            len(failed_batches),
            total_batches,
        )
        update_query_tracker(
            tracker,
            service.sync_stats,
            ResearchAPIQueryTracker.Status.PARTIAL_FAILURE,
            exception_details={"failed batches": failed_batches},
        )
    else:
        logger.info(
            "%s: Completed sync. Total videos retrieved: %d. "
            "Created %d users, %d videos, %d hashtags, %d music entries. "
            "Parameters: {batch_size: %d, query_end_date: %s, query_start_date: %s}",
            task_name,
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
    batch_size: int = 20,
    query_start_date: str | None = None,
    query_end_date: str | None = None,
) -> None:
    _run_query_task(
        "query_videos_by_user",
        TikTokUser.objects.filter(monitor_api=True),
        "get_user_videos",
        batch_size,
        query_start_date,
        query_end_date,
        TikTokUser,
    )


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
    _run_query_task(
        "query_videos_by_hashtag",
        TikTokHashtag.objects.filter(monitor_api=True),
        "get_hashtag_videos",
        batch_size,
        query_start_date,
        query_end_date,
        TikTokHashtag,
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
    exception_details: dict | None = None,
) -> None:
    query_tracker.end_time = timezone.now()
    query_tracker.query_status = query_status
    query_tracker.query_result = sync_stats
    query_tracker.exception_details = exception_details
    query_tracker.save()
