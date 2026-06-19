from datetime import UTC, datetime


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
