"""Research API credential pairs and the cross-run rate-limit exhaustion hint.

The Research API sync can be configured with a primary and an optional secondary
``(api_key, api_secret)`` pair. When the primary is rate-limited mid-run,
:class:`~ddcs.metadata.research_api.service.ResearchAPIService` fails over to the
secondary. To stop every subsequently-constructed service (notably the fresh
service built per ``(target, date)`` pair in ``backfill_missing_syncs``) from
wasting a request re-discovering that the primary is dead, the abandoning service
records a short-lived hint in Redis keyed by credential index. The hint expires at
the next TikTok quota reset (00:00 UTC).

Every Redis call here is best-effort: if Redis is unavailable the service simply
degrades to stateless behaviour (always start on the primary, fail over on a live
rate-limit response).
"""

import logging
from datetime import UTC, datetime, timedelta

from django.conf import settings
from redis import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

_EXHAUSTION_KEY_PREFIX = "ddcs:research_api:credential_exhausted:"


def get_research_api_credentials() -> list[tuple[str, str]]:
    """Return the ordered list of configured ``(api_key, api_secret)`` pairs.

    Index 0 is the primary pair, index 1 (if present) the secondary. A pair is
    included only if both halves are set, so an empty or half-configured
    secondary disables failover entirely.
    """
    candidates = [
        (settings.TIKTOK_RESEARCH_API_KEY, settings.TIKTOK_RESEARCH_API_SECRET),
        (
            settings.TIKTOK_RESEARCH_API_KEY_SECONDARY,
            settings.TIKTOK_RESEARCH_API_SECRET_SECONDARY,
        ),
    ]
    return [(key, secret) for key, secret in candidates if key and secret]


def _redis_client() -> Redis:
    return Redis.from_url(settings.CELERY_BROKER_URL)


def seconds_until_next_utc_midnight(now: datetime | None = None) -> int:
    """Seconds from ``now`` (default: current UTC time) until the next 00:00 UTC.

    Always at least 1 so it is a valid Redis TTL.
    """
    now = now or datetime.now(tz=UTC)
    next_day = (now + timedelta(days=1)).date()
    reset = datetime(next_day.year, next_day.month, next_day.day, tzinfo=UTC)
    return max(1, int((reset - now).total_seconds()))


def mark_credentials_exhausted(index: int, *, client: Redis | None = None) -> None:
    """Flag the credential pair at ``index`` as rate-limited until the UTC reset."""
    try:
        (client or _redis_client()).set(
            f"{_EXHAUSTION_KEY_PREFIX}{index}",
            b"1",
            ex=seconds_until_next_utc_midnight(),
        )
    except (RedisError, OSError):
        logger.warning(
            "Could not set Research API exhaustion hint for credential index %d.",
            index,
            exc_info=True,
        )


def is_credentials_exhausted(index: int, *, client: Redis | None = None) -> bool:
    """Whether the credential pair at ``index`` is currently flagged exhausted.

    Returns ``False`` if the hint cannot be read (Redis down) so the caller
    falls back to trying the pair.
    """
    key = f"{_EXHAUSTION_KEY_PREFIX}{index}"
    try:
        return bool((client or _redis_client()).exists(key))
    except (RedisError, OSError):
        logger.warning(
            "Could not read Research API exhaustion hint for credential index %d; "
            "proceeding without it.",
            index,
            exc_info=True,
        )
        return False
