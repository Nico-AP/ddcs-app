import logging
from datetime import UTC, datetime

from django.db import connection

logger = logging.getLogger(__name__)


def recover_db_connection() -> None:
    """Drop a possibly-poisoned DB connection before recovery-path writes.

    ``SoftTimeLimitExceeded`` can be raised by the signal handler while
    psycopg is mid-query, leaving the connection unusable (query still in
    progress). Any ORM write afterwards then raises or blocks until the hard
    time limit SIGKILLs the worker. We close the socket unconditionally
    rather than probe it. Django reconnects lazily on the next query.
    """
    try:
        connection.close()
    except Exception:  # noqa: BLE001
        logger.warning("Failed to close DB connection during recovery.", exc_info=True)


def infer_publication_date_from_id(tiktok_id: int) -> datetime:
    """Infers publication date from TikTok ID.

    Based on the work by Steel et al. (https://doi.org/10.48550/arXiv.2504.13279),
    the function infers a TikTok video's publication date from its ID by
    first converting the ID to its binary representation and then converting the
    first 32 bits back to base 10, which is equivalent to the timestamp when the
    video was published.

    Args:
        tiktok_id: TikTok ID

    Returns:
        datetime: The inferred publication date
    """
    binary_id = bin(tiktok_id).replace("b", "")
    binary_ts = binary_id[:32]
    ts = int(binary_ts, 2)
    return datetime.fromtimestamp(ts, tz=UTC)
