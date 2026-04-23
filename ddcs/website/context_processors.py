from django.conf import settings
from django.http import HttpRequest


def analytics(request: HttpRequest) -> dict[str, str | None]:
    """Adds the analytics script ID to the context."""

    return {
        "ANALYTICS_SCRIPT_SRC": settings.ANALYTICS_SCRIPT_SRC,
        "ANALYTICS_WEBSITE_ID": settings.ANALYTICS_WEBSITE_ID,
    }
