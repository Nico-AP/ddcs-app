"""Priorities of videos for the prioritised video API.

A priority is derived from facts that are stored elsewhere, at query time:
whether a donor watched, liked or bookmarked the video (``DonationVideoInfos``),
whether it is listed in Datapods (``in_datapods``) and whether the
Research API delivered it (``APIVideoInfos``). It is not stored, because
these facts can change after one another were recorded.
"""

from django.db import models
from django.db.models import Case, Exists, OuterRef, Q, QuerySet, When

from ddcs.metadata.models import TikTokVideo
from ddcs.metadata.research_api.models import APIVideoInfos
from ddcs.metadata.scraper.models import VideoInfosScraped


class VideoPriority(models.IntegerChoices):
    # Watched, liked or bookmarked by a donor at any time (or imported from
    # Datapods), and delivered by the Research API.
    DONATED_AND_RESEARCH_API = 4
    # Watched, liked or bookmarked by a donor within the watch window (or
    # imported from Datapods); no Research API infos.
    DONATED_IN_WINDOW = 3
    # Delivered by the Research API; in no donation, not from Datapods.
    RESEARCH_API_ONLY = 2
    OTHER = 1


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

# Mutually exclusive, and together they cover every video. Spelled out per
# priority (rather than as "none of the above") so that a filter on one
# priority stays a plain condition the database can plan for.
PRIORITY_CONDITIONS = {
    VideoPriority.DONATED_AND_RESEARCH_API: _DONATED & Q(HAS_API_INFOS),
    VideoPriority.DONATED_IN_WINDOW: _INTERACTION_IN_WINDOW & Q(~HAS_API_INFOS),
    VideoPriority.RESEARCH_API_ONLY: _NOT_DONATED & Q(HAS_API_INFOS),
    # A video donated outside the window counts as "everything else" here.
    VideoPriority.OTHER: _NO_INTERACTION_IN_WINDOW & Q(~HAS_API_INFOS),
}


def annotate_priority(queryset: QuerySet[TikTokVideo]) -> QuerySet[TikTokVideo]:
    return queryset.annotate(
        priority=Case(
            *(
                When(condition, then=priority.value)
                for priority, condition in PRIORITY_CONDITIONS.items()
                if priority != VideoPriority.OTHER
            ),
            default=VideoPriority.OTHER.value,
            output_field=models.SmallIntegerField(),
        )
    )
