from datetime import datetime

import django_filters
from django.db.models import Exists, OuterRef, Q, QuerySet

from ddcs.metadata.models import TikTokVideo, TikTokVideoClassification
from ddcs.metadata.priority import (
    HAS_API_INFOS,
    HAS_SCRAPED_INFOS,
    METADATA_SOURCE_CONDITIONS,
    PRIORITY_CONDITIONS,
    MetadataSource,
    VideoPriority,
)
from ddcs.metadata.research_api.models import APIVideoInfos


class NumberInFilter(django_filters.BaseInFilter, django_filters.NumberFilter):
    """Accepts comma-separated integers, e.g. ?id_tiktok=1,2,3"""


class CharInFilter(django_filters.BaseInFilter, django_filters.CharFilter):
    """Accepts comma-separated strings, e.g. ?usernames=annalise,pirmin"""


class TikTokVideoFilter(django_filters.FilterSet):
    """
    NOTE: filter_create_date_from/to, filter_region_codes, and
    filter_updated_since all rely on the queryset already being annotated
    with `latest_api_info_id`, `latest_create_time`, and `latest_region_code`
    respectively (see TikTokVideoList.get_queryset). This FilterSet is not safe
    to use standalone against an un-annotated TikTokVideo queryset.
    """

    id_tiktok = NumberInFilter(field_name="id_tiktok", lookup_expr="in")
    usernames = CharInFilter(field_name="user__name", lookup_expr="in")
    monitored_users = django_filters.BooleanFilter(field_name="user__monitor_api")
    create_date_from = django_filters.DateFilter(
        field_name="latest_create_time",
        lookup_expr="date__gte",
    )
    create_date_to = django_filters.DateFilter(
        field_name="latest_create_time",
        lookup_expr="date__lte",
    )
    create_date = django_filters.DateFilter(
        field_name="latest_create_time", lookup_expr="date"
    )
    region_codes = CharInFilter(field_name="latest_region_code", lookup_expr="in")
    keywords = CharInFilter(method="filter_keywords")
    has_api_infos = django_filters.BooleanFilter(method="filter_has_api_infos")
    has_classifications = django_filters.BooleanFilter(
        method="filter_has_classifications"
    )

    updated_since = django_filters.IsoDateTimeFilter(method="filter_updated_since")

    class Meta:
        model = TikTokVideo
        fields = []

    def filter_updated_since(
        self, queryset: QuerySet[TikTokVideo], name: str, value: datetime
    ) -> QuerySet[TikTokVideo]:
        newer_api_info = APIVideoInfos.objects.filter(
            video=OuterRef("pk"), created_at__gt=value
        )
        return queryset.filter(Q(updated_at__gt=value) | Q(Exists(newer_api_info)))

    def filter_has_api_infos(
        self, queryset: QuerySet[TikTokVideo], name: str, value: bool
    ) -> QuerySet[TikTokVideo]:
        return queryset.filter(latest_api_info_id__isnull=not value)

    def filter_has_classifications(
        self, queryset: QuerySet[TikTokVideo], name: str, value: bool
    ) -> QuerySet[TikTokVideo]:
        has_classification = Exists(
            TikTokVideoClassification.objects.filter(video=OuterRef("pk"))
        )
        return queryset.filter(has_classification if value else ~has_classification)

    def filter_keywords(
        self, queryset: QuerySet[TikTokVideo], name: str, value: str
    ) -> QuerySet[TikTokVideo]:
        return queryset.filter(
            Exists(
                TikTokVideo.keywords.through.objects.filter(
                    tiktokvideo_id=OuterRef("pk"), keyword__name__in=value
                )
            )
        )


class PrioritisedTikTokVideoFilter(TikTokVideoFilter):
    """Filters of the prioritised video list; see the note on the parent."""

    priority = django_filters.TypedMultipleChoiceFilter(
        choices=VideoPriority.choices,
        coerce=int,
        widget=django_filters.widgets.CSVWidget,
        method="filter_priority",
        help_text="One or several priorities, comma-separated, e.g. 4,3",
    )
    metadata_source = django_filters.ChoiceFilter(
        choices=MetadataSource.choices, method="filter_metadata_source"
    )
    has_metadata = django_filters.BooleanFilter(method="filter_has_metadata")

    def filter_priority(
        self, queryset: QuerySet[TikTokVideo], name: str, value: list[int]
    ) -> QuerySet[TikTokVideo]:
        if not value:
            return queryset
        condition = Q()
        for priority in set(value):
            condition |= PRIORITY_CONDITIONS[VideoPriority(priority)]
        return queryset.filter(condition)

    def filter_metadata_source(
        self, queryset: QuerySet[TikTokVideo], name: str, value: str
    ) -> QuerySet[TikTokVideo]:
        return queryset.filter(METADATA_SOURCE_CONDITIONS[MetadataSource(value)])

    def filter_has_metadata(
        self, queryset: QuerySet[TikTokVideo], name: str, value: bool
    ) -> QuerySet[TikTokVideo]:
        if value:
            return queryset.filter(Q(HAS_API_INFOS) | Q(HAS_SCRAPED_INFOS))
        return queryset.filter(~HAS_API_INFOS, ~HAS_SCRAPED_INFOS)

    def filter_updated_since(
        self, queryset: QuerySet[TikTokVideo], name: str, value: datetime
    ) -> QuerySet[TikTokVideo]:
        # Everything that changes what is served here also moves the video's
        # (indexed) ``updated_at``: new Research API infos
        # (ResearchAPIService._sync_video), a scrape (ScraperService._store)
        # and a donation (donations.service.record_donated_videos). One
        # condition on it is enough, and the only form an index can serve.
        return queryset.filter(updated_at__gt=value)
