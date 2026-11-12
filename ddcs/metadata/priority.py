"""Priorities of videos for the prioritised video API.

A priority is derived from facts that are stored elsewhere, at query time:
whether a donor watched, liked or bookmarked the video (``DonationVideoInfos``),
whether it is listed in Datapods (``in_datapods``) and whether the
Research API delivered it (``APIVideoInfos``). It is not stored, because
these facts can change after one another were recorded.

A video can also be given a priority by hand (``TikTokVideo.manual_priority``,
see the ``set_manual_priority`` command). That number replaces the derived
one, whatever it is: it can raise a video above every derived priority (5 or
higher) or pin it to one of them (1 to 4), also downwards. The API reports it
alongside, so a client can tell a manual priority from a derived one.
"""

from django.db import models
from django.db.models import Case, Exists, F, OuterRef, Q, QuerySet, When

from ddcs.metadata.models import TikTokVideo
from ddcs.metadata.research_api.models import APIVideoInfos
from ddcs.metadata.scraper.models import VideoInfosScraped


class VideoPriority(models.IntegerChoices):
    """The derived priorities. Manual ones can be any number from
    ``MANUAL_PRIORITY_MIN`` on, also one of these."""

    # Watched, liked or bookmarked by a donor at any time (or imported from
    # Datapods), and delivered by the Research API.
    DONATED_AND_RESEARCH_API = 4
    # Watched, liked or bookmarked by a donor within the watch window (or
    # imported from Datapods); no Research API infos.
    DONATED_IN_WINDOW = 3
    # Delivered by the Research API; in no donation, not from Datapods.
    RESEARCH_API_ONLY = 2
    OTHER = 1


MANUAL_PRIORITY_MIN = 1


class MetadataSource(models.TextChoices):
    RESEARCH_API = "research_api"
    SCRAPED = "scraped"


HAS_API_INFOS = Exists(APIVideoInfos.objects.filter(video=OuterRef("pk")))
HAS_SCRAPED_INFOS = Exists(VideoInfosScraped.objects.filter(video=OuterRef("pk")))

# Research API infos take precedence wherever a video has both.
METADATA_SOURCE_CONDITIONS = {
    MetadataSource.RESEARCH_API: Q(HAS_API_INFOS),
    MetadataSource.SCRAPED: Q(~HAS_API_INFOS) & Q(HAS_SCRAPED_INFOS),
}

_NOT_MANUAL = Q(manual_priority__isnull=True)
# Videos listed in Datapods rank like videos donated in the window.
_FROM_DATAPODS = Q(in_datapods=True)
_DONATED = Q(donation_infos__isnull=False) | _FROM_DATAPODS
_NOT_DONATED = Q(donation_infos__isnull=True) & ~_FROM_DATAPODS
_INTERACTION_IN_WINDOW = (
    Q(donation_infos__last_interaction_in_window_at__isnull=False) | _FROM_DATAPODS
)
_NO_INTERACTION_IN_WINDOW = (
    Q(donation_infos__last_interaction_in_window_at__isnull=True) & ~_FROM_DATAPODS
)

# Mutually exclusive, and together they cover every video without a manual
# priority. Spelled out per priority (rather than as "none of the above") so
# that a filter on one priority stays a plain condition the database can
# plan for.
PRIORITY_CONDITIONS = {
    VideoPriority.DONATED_AND_RESEARCH_API: _NOT_MANUAL & _DONATED & Q(HAS_API_INFOS),
    VideoPriority.DONATED_IN_WINDOW: _NOT_MANUAL
    & _INTERACTION_IN_WINDOW
    & Q(~HAS_API_INFOS),
    VideoPriority.RESEARCH_API_ONLY: _NOT_MANUAL & _NOT_DONATED & Q(HAS_API_INFOS),
    # A video donated outside the window counts as "everything else" here.
    VideoPriority.OTHER: _NOT_MANUAL & _NO_INTERACTION_IN_WINDOW & Q(~HAS_API_INFOS),
}


def priority_condition(priority: int) -> Q:
    """The videos that have ``priority``, derived or set by hand."""
    manual = Q(manual_priority=priority)
    if priority in VideoPriority.values:
        return manual | PRIORITY_CONDITIONS[VideoPriority(priority)]
    return manual


def annotate_priority(queryset: QuerySet[TikTokVideo]) -> QuerySet[TikTokVideo]:
    return queryset.annotate(
        priority=Case(
            When(manual_priority__isnull=False, then=F("manual_priority")),
            *(
                When(condition, then=priority.value)
                for priority, condition in PRIORITY_CONDITIONS.items()
                if priority != VideoPriority.OTHER
            ),
            default=VideoPriority.OTHER.value,
            output_field=models.SmallIntegerField(),
        )
    )
