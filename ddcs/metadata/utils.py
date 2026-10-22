import logging
from collections.abc import Iterable
from datetime import UTC, datetime

from django.db import connection

from ddcs.metadata.models import DataOrigins, TikTokVideo

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


def video_pks(
    id_tiktoks: Iterable[int], added_by: DataOrigins = DataOrigins.DONATION
) -> dict[int, int]:
    """TikTok ID -> primary key of the videos, creating rows that are missing.

    Rows created get ``added_by``; existing rows keep theirs.
    """

    def lookup(ids: Iterable[int]) -> dict[int, int]:
        return dict(
            TikTokVideo.objects.filter(id_tiktok__in=ids).values_list("id_tiktok", "pk")
        )

    pk_by_id = lookup(id_tiktoks)
    missing = [id_tiktok for id_tiktok in id_tiktoks if id_tiktok not in pk_by_id]
    if missing:
        TikTokVideo.objects.bulk_create(
            [
                TikTokVideo(id_tiktok=id_tiktok, added_by=added_by)
                for id_tiktok in missing
            ],
            ignore_conflicts=True,
        )
        pk_by_id.update(lookup(missing))
    return pk_by_id
