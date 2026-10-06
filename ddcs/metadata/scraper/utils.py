from typing import Any, TypedDict


class TikTokHashtag(TypedDict):
    id: int
    name: str


def int_or_none(value: Any) -> int | None:  # noqa: ANN401
    """Converts value to integer or returns None if not possible.

    Args:
        value: Value to convert to integer.

    Returns:
        Integer representation of value or None.
    """
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
