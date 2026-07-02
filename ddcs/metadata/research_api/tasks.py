import logging
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import Any

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.db.models import Exists, OuterRef, QuerySet
from django.utils import timezone
from redis import Redis
from tiktok_metadata_kit.research_api import ResearchAPIRateLimitExceededError

from ddcs.metadata.models import (
    ResearchAPIQueryTracker,
    SyncAttempt,
    TikTokHashtag,
    TikTokUser,
)
from ddcs.metadata.research_api.service import ResearchAPIService

logger = logging.getLogger(__name__)


class _Retry(Enum):
    """How the outer task should retry after a run finishes.

    - ``NONE``: no retry (success or nothing to do).
    - ``HALVE_BATCH``: retry with ``batch_size // 2`` — used when smaller
      batches help (isolate poison-pill items on partial failure, fit more
      into the time budget on soft-time-limit).
    - ``SAME_BATCH``: retry with the same batch size — used when the
      failure is size-independent (rate limits).
    """

    NONE = "none"
    HALVE_BATCH = "halve_batch"
    SAME_BATCH = "same_batch"


@dataclass(frozen=True)
class _RunResult:
    """Outcome of a single ``_run_query_task`` invocation.

    - ``retry``: how the outer task should schedule a retry, if at all.
    - ``pages_consumed``: number of API result pages returned during this
      run. Each page is billed as one Research API quota point, so this
      is what the backfill task decrements from its budget.
    """

    retry: _Retry
    pages_consumed: int


@dataclass(frozen=True)
class _SyncTargetConfig:
    """Static per-sync_target config that the shared runner needs.

    Two sync targets are supported: TikTok users (queried by username) and
    TikTok hashtags used as keyword targets. Both write SyncAttempt rows
    into the same table via the FK named in ``sync_attempt_field``.
    """

    task_name: str
    model: type[TikTokUser] | type[TikTokHashtag]
    sync_attempt_field: str  # "user" or "hashtag"
    service_method_name: str


_USER_SYNC_TARGET_CONFIG = _SyncTargetConfig(
    task_name="daily_sync_users",
    model=TikTokUser,
    sync_attempt_field="user",
    service_method_name="get_user_videos",
)
_KEYWORD_SYNC_TARGET_CONFIG = _SyncTargetConfig(
    task_name="daily_sync_keywords",
    model=TikTokHashtag,
    sync_attempt_field="hashtag",
    service_method_name="get_videos_by_keywords",
)


# Shared Celery config for the daily Research API query tasks.
#
# Retry sequence (base 60s, doubling, capped at 10 min, 3 retries):
#     1, 2, 4 min  ≈ 7 min total window.
# The primary task's job is transient-failure recovery within a single
# scheduled run; the backfill task catches everything else, so the retry
# window can stay short. `acks_late=True` means the broker redelivers on
# worker crash.
_QUERY_TASK_OPTIONS: dict[str, Any] = {
    "bind": True,
    "acks_late": True,
    "retry_backoff": 60,
    "retry_backoff_max": 600,
    "retry_jitter": True,
    "max_retries": 3,
    "soft_time_limit": 55 * 60,
    "time_limit": 60 * 60,
}


def _parse_target_date(target_date: str | None) -> date:
    """Parse the task's ``target_date`` kwarg (ISO string) into a ``date``.

    ``None`` defaults to ``today - 4 days`` — the standard daily-sync
    target, since TikTok's API has ~4-day publication delay.
    """
    if target_date is None:
        return timezone.localdate() - timedelta(days=4)
    return date.fromisoformat(target_date)


def _gap_items(sync_target: _SyncTargetConfig, target_date: date) -> QuerySet:
    """Items still needing a successful sync for ``target_date``.

    Uses the ``SyncAttempt`` table as the source of truth — any item
    without a ``SUCCESS`` attempt for this date is included. Ordered by
    monitoring priority so higher-priority items get quota first.
    """
    already_synced = SyncAttempt.objects.filter(
        **{sync_target.sync_attempt_field: OuterRef("pk")},
        target_date=target_date,
        status=SyncAttempt.Status.SUCCESS,
    )
    return (
        sync_target.model.objects.filter(monitor_api=True)
        .annotate(_is_synced=Exists(already_synced))
        .filter(_is_synced=False)
        .order_by("-monitoring_priority_api", "id")
    )


def _record_sync_attempts(  # noqa: PLR0913
    sync_target: _SyncTargetConfig,
    item_ids: list[int],
    target_date: date,
    status: SyncAttempt.Status,
    tracker: ResearchAPIQueryTracker | None,
    error_details: dict | None = None,
) -> None:
    """Insert one SyncAttempt per item, all with the same status/tracker."""
    if not item_ids:
        return

    fk_field = f"{sync_target.sync_attempt_field}_id"
    SyncAttempt.objects.bulk_create(
        [
            SyncAttempt(
                **{fk_field: item_id},
                target_date=target_date,
                status=status,
                error_details=error_details,
                tracker=tracker,
            )
            for item_id in item_ids
        ]
    )


def _run_query_task(
    sync_target: _SyncTargetConfig,
    target_date: date,
    batch_size: int,
    items: list[dict] | None = None,
) -> _RunResult:
    """Shared runner for the daily / backfill sync tasks.

    Queries the API in batches for a set of monitored ``items`` on a
    specific ``target_date``, and writes one ``SyncAttempt`` per (item,
    target_date) with the outcome. The tracker holds run-level metadata;
    the sync attempts hold per-item outcome.

    If ``items`` is None, defaults to every monitored item missing a
    successful ``SyncAttempt`` for ``target_date`` (the daily-sync case).
    Callers that need to cap the item set (backfill) pass ``items``
    explicitly.

    Returns a :class:`_RunResult` bundling the retry decision and the
    number of API pages consumed during the run — the latter is what
    the backfill task decrements from its quota budget.
    """
    logger.info(
        "Starting %s for target_date=%s.",
        sync_target.task_name,
        target_date.isoformat(),
    )

    if items is None:
        items = list(_gap_items(sync_target, target_date).values("id", "name"))

    if not items:
        logger.info(
            "No gaps to fill for %s on %s.",
            sync_target.task_name,
            target_date.isoformat(),
        )
        return _RunResult(retry=_Retry.NONE, pages_consumed=0)

    tracker = register_query_tracker(
        sync_target.task_name,
        {
            "target_date": target_date.isoformat(),
            "batch_size": batch_size,
            "n_items": len(items),
        },
    )

    service = ResearchAPIService()
    service_method = getattr(service, sync_target.service_method_name)
    # Snapshot page counter so we can report the delta consumed by this run —
    # a fresh service always starts at 0 in real code; the delta pattern keeps
    # test doubles (which share the counter across invocations) accurate too.
    pages_before = service.sync_stats["pages_retrieved"]
    total_batches = (len(items) + batch_size - 1) // batch_size
    failed_batches: list[dict] = []

    for batch_idx, i in enumerate(range(0, len(items), batch_size), start=1):
        batch = items[i : i + batch_size]
        batch_ids = [b["id"] for b in batch]
        batch_names = [b["name"] for b in batch]

        try:
            service_method(batch_names, start_date=target_date, end_date=target_date)
            _record_sync_attempts(
                sync_target, batch_ids, target_date, SyncAttempt.Status.SUCCESS, tracker
            )
            logger.info(
                "%s: batch %d/%d done (%d items). Cumulative videos: %d.",
                sync_target.task_name,
                batch_idx,
                total_batches,
                len(batch),
                service.sync_stats["videos_retrieved"],
            )

        except SoftTimeLimitExceeded:
            logger.warning(
                "%s hit soft time limit after %d/%d batches.",
                sync_target.task_name,
                batch_idx,
                total_batches,
            )
            _record_sync_attempts(
                sync_target, batch_ids, target_date, SyncAttempt.Status.TIMEOUT, tracker
            )
            update_query_tracker(
                tracker,
                service.sync_stats,
                ResearchAPIQueryTracker.Status.SOFT_TIME_LIMIT_EXCEEDED,
                exception_details=(
                    {"failed batches": failed_batches} if failed_batches else None
                ),
            )
            return _RunResult(
                retry=_Retry.HALVE_BATCH,
                pages_consumed=service.sync_stats["pages_retrieved"] - pages_before,
            )

        except ResearchAPIRateLimitExceededError:
            logger.warning(
                "%s hit rate limit after %d/%d batches.",
                sync_target.task_name,
                batch_idx,
                total_batches,
            )
            _record_sync_attempts(
                sync_target,
                batch_ids,
                target_date,
                SyncAttempt.Status.RATE_LIMITED,
                tracker,
            )
            update_query_tracker(
                tracker,
                service.sync_stats,
                ResearchAPIQueryTracker.Status.RATE_LIMIT_EXCEEDED,
                exception_details=(
                    {"failed batches": failed_batches} if failed_batches else None
                ),
            )
            return _RunResult(
                retry=_Retry.SAME_BATCH,
                pages_consumed=service.sync_stats["pages_retrieved"] - pages_before,
            )

        except Exception as exc:
            msg = (
                f"{sync_target.task_name}, batch {batch_idx}/{total_batches} failed "
                f"with {type(exc).__name__}: {exc}."
            )
            logger.exception(msg)
            failed_batches.append({"batch": batch_idx, "error": msg})
            _record_sync_attempts(
                sync_target,
                batch_ids,
                target_date,
                SyncAttempt.Status.API_ERROR,
                tracker,
                error_details={"type": type(exc).__name__, "message": str(exc)},
            )

    if failed_batches:
        logger.warning(
            "%s completed with %d/%d failed batches.",
            sync_target.task_name,
            len(failed_batches),
            total_batches,
        )
        update_query_tracker(
            tracker,
            service.sync_stats,
            ResearchAPIQueryTracker.Status.PARTIAL_FAILURE,
            exception_details={"failed batches": failed_batches},
        )
        return _RunResult(
            retry=_Retry.HALVE_BATCH,
            pages_consumed=service.sync_stats["pages_retrieved"],
        )

    logger.info(
        "%s: Completed sync for %s. Retrieved %d videos on %d pages. "
        "Created %d users, %d videos, %d hashtags, %d music entries.",
        sync_target.task_name,
        target_date.isoformat(),
        service.sync_stats["videos_retrieved"],
        service.sync_stats["pages_retrieved"],
        service.sync_stats["users_created"],
        service.sync_stats["videos_created"],
        service.sync_stats["hashtags_created"],
        service.sync_stats["music_created"],
    )
    update_query_tracker(
        tracker, service.sync_stats, ResearchAPIQueryTracker.Status.COMPLETED
    )
    return _RunResult(
        retry=_Retry.NONE,
        pages_consumed=service.sync_stats["pages_retrieved"],
    )


def _maybe_retry(
    task: Any,  # noqa: ANN401
    retry: _Retry,
    batch_size: int,
    target_date: str | None,
) -> None:
    """Re-enqueue ``task`` per ``retry`` strategy, or return without re-queuing.

    Items with a successful SyncAttempt for ``target_date`` are excluded
    on the next attempt via the queryset filter, so retries only touch
    items that failed or didn't fit in the previous attempt.
    """
    if retry is _Retry.NONE:
        return

    next_batch_size = (
        batch_size if retry is _Retry.SAME_BATCH else max(1, batch_size // 2)
    )
    raise task.retry(kwargs={"batch_size": next_batch_size, "target_date": target_date})


@shared_task(**_QUERY_TASK_OPTIONS)
def daily_sync_users(
    self,  # noqa: ANN001
    target_date: str | None = None,
    batch_size: int = 20,
) -> None:
    parsed = _parse_target_date(target_date)
    result = _run_query_task(_USER_SYNC_TARGET_CONFIG, parsed, batch_size)
    _maybe_retry(self, result.retry, batch_size, target_date or parsed.isoformat())


@shared_task(**_QUERY_TASK_OPTIONS)
def daily_sync_keywords(
    self,  # noqa: ANN001
    target_date: str | None = None,
    batch_size: int = 50,
) -> None:
    parsed = _parse_target_date(target_date)
    result = _run_query_task(_KEYWORD_SYNC_TARGET_CONFIG, parsed, batch_size)
    _maybe_retry(self, result.retry, batch_size, target_date or parsed.isoformat())


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
    query_tracker.query_exception_details = exception_details
    query_tracker.save()


# ---------------------------------------------------------------------------
# Backfill task
# ---------------------------------------------------------------------------

_BACKFILL_LOCK_KEY = "ddcs:research_api:backfill_lock"
# Order matters: users get first pick of the quota, then keywords.
_BACKFILL_ORDER: list[tuple[_SyncTargetConfig, int]] = [
    (_USER_SYNC_TARGET_CONFIG, 20),  # config, batch_size
    (_KEYWORD_SYNC_TARGET_CONFIG, 50),
]


def _backfill_target_dates() -> list[date]:
    """Dates the backfill task considers, most recent first.

    Ranges from ``today - 4 days`` back to ``settings.API_MONITORING_START_DATE``
    inclusive. Recent dates first so a quota-limited run at least closes
    the freshest gaps before working backwards through history.
    """
    start = settings.API_MONITORING_START_DATE
    end = timezone.localdate() - timedelta(days=4)
    if end < start:
        return []
    return [end - timedelta(days=i) for i in range((end - start).days + 1)]


@shared_task(
    bind=True,
    acks_late=True,
    max_retries=0,
    soft_time_limit=110 * 60,
    time_limit=120 * 60,
)
def backfill_missing_syncs(
    self,  # noqa: ANN001
) -> None:
    """Close coverage gaps in :class:`SyncAttempt`, prioritising users first.

    Iterates ``(sync_target, target_date)`` pairs in priority order — all
    users across all backfill dates, then keywords — and for each pair
    processes every remaining gap. Newer dates are processed first
    within each sync_target.

    There is no per-run page budget: after the daily sync has run,
    whatever quota is left in the day is fair game and unused quota
    doesn't carry over. Natural governors keep this safe:

    * The Celery soft time limit caps wall-clock work per run.
    * Hitting the API rate limit ends this run (see below); the next
      scheduled run picks up where it left off.
    * A Redis lock prevents overlapping invocations from stacking work.

    On rate-limit, the whole task returns early instead of iterating to
    the next ``(target, date)`` and re-experiencing the same limit.
    The lock is held only for the duration of this run, so
    the next scheduled run can proceed once the rate-limit window has
    passed.
    """
    redis_client = Redis.from_url(settings.CELERY_BROKER_URL)
    lock = redis_client.lock(_BACKFILL_LOCK_KEY, timeout=self.soft_time_limit + 60)
    if not lock.acquire(blocking=False):
        logger.info("backfill_missing_syncs: lock held; skipping this run.")
        return

    try:
        for sync_target, batch_size in _BACKFILL_ORDER:
            for target_date in _backfill_target_dates():
                items = list(_gap_items(sync_target, target_date).values("id", "name"))
                if not items:
                    continue

                logger.info(
                    "backfill_missing_syncs: %s %s → %d items.",
                    sync_target.task_name,
                    target_date.isoformat(),
                    len(items),
                )

                result = _run_query_task(
                    sync_target, target_date, batch_size, items=items
                )
                if result.retry is _Retry.SAME_BATCH:
                    # Rate-limited. Moving to the next (target, date) would
                    # just hit the same limit again; bail out and let the
                    # next scheduled run pick up.
                    logger.info(
                        "backfill_missing_syncs: hit rate limit; stopping this run."
                    )
                    return
    finally:
        try:
            lock.release()
        except Exception:  # noqa: BLE001
            # Lock may have expired between acquire and release; not fatal.
            logger.warning(
                "backfill_missing_syncs: could not release lock cleanly.",
                exc_info=True,
            )
