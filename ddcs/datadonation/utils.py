from django.conf import settings
from django.urls import NoReverseMatch, reverse


def get_step_url(steps: list[str], current_step: int, slug: str | None) -> str:
    """Defensive resolution of url, allowing for both urls that need and
    do not need slug-kwarg.
    """
    if slug is None:
        slug = settings.TIKTOK_DDM_PROJECT_SLUG

    try:
        return reverse(steps[current_step], kwargs={"slug": slug})
    except NoReverseMatch:
        # Fallback for URLs hard-coding the "tiktok" slug.
        return reverse(steps[current_step])


def get_current_step_url(steps: list[str], current_step: int, slug: str | None) -> str:
    """Defensive resolution of current step url, allowing for both urls that need
    and do not need slug-kwarg.
    """
    return get_step_url(steps, current_step, slug)


def get_next_step_url(steps: list[str], current_step: int, slug: str | None) -> str:
    """Defensive resolution of next step url, allowing for both urls that need and
    do not need slug-kwarg.
    """
    current_step += 1
    return get_step_url(steps, current_step, slug)
