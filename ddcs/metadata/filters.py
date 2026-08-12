from datetime import date, datetime

import django_filters
from django.db.models import Q, QuerySet

from ddcs.metadata.models import TikTokVideo
from ddcs.metadata.research_api.models import APIVideoInfos


class NumberInFilter(django_filters.BaseInFilter, django_filters.NumberFilter):
    """Accepts comma-separated integers, e.g. ?id_tiktok=1,2,3"""


class CharInFilter(django_filters.BaseInFilter, django_filters.CharFilter):
    """Accepts comma-separated strings, e.g. ?usernames=annalise,pirmin"""


class TikTokVideoFilter(django_filters.FilterSet):
    """
    NOTE: filter_create_date_from/to, filter_region_codes, and
    filter_updated_since all rely on the queryset already being annotated
    with `latest_api_info_id` (see TikTokVideoList.get_queryset). This
    FilterSet is not safe to use standalone against an un-annotated
    TikTokVideo queryset.
    """

    id_tiktok = NumberInFilter(field_name="id_tiktok", lookup_expr="in")
    usernames = CharInFilter(field_name="user__name", lookup_expr="in")
    monitored_users = django_filters.BooleanFilter(field_name="user__is_monitored")
    create_date_from = django_filters.DateFilter(method="filter_create_date_from")
    create_date_to = django_filters.DateFilter(method="filter_create_date_to")
    region_codes = CharInFilter(method="filter_region_codes")
    keywords = CharInFilter(field_name="keywords__name", lookup_expr="in")
    has_api_infos = django_filters.BooleanFilter(method="filter_has_api_infos")

    updated_since = django_filters.IsoDateTimeFilter(method="filter_updated_since")

    class Meta:
        model = TikTokVideo
        fields = []  # all fields declared explicitly above

    def filter_create_date_from(
        self, queryset: QuerySet[TikTokVideo], name: str, value: date
    ) -> QuerySet[TikTokVideo]:
        matching_video_ids = APIVideoInfos.objects.filter(
            pk__in=queryset.values("latest_api_info_id"),
            create_time__date__gte=value,
        ).values("video_id")
        return queryset.filter(pk__in=matching_video_ids)

    def filter_create_date_to(
        self, queryset: QuerySet[TikTokVideo], name: str, value: date
    ) -> QuerySet[TikTokVideo]:
        matching_video_ids = APIVideoInfos.objects.filter(
            pk__in=queryset.values("latest_api_info_id"),
            create_time__date__lte=value,
        ).values("video_id")
        return queryset.filter(pk__in=matching_video_ids)

    def filter_region_codes(
        self, queryset: QuerySet[TikTokVideo], name: str, value: list[str]
    ) -> QuerySet[TikTokVideo]:
        matching_video_ids = APIVideoInfos.objects.filter(
            pk__in=queryset.values("latest_api_info_id"),
            region_code__in=value,
        ).values("video_id")
        return queryset.filter(pk__in=matching_video_ids)

    def filter_updated_since(
        self, queryset: QuerySet[TikTokVideo], name: str, value: datetime
    ) -> QuerySet[TikTokVideo]:
        videos_with_new_info = APIVideoInfos.objects.filter(
            pk__in=queryset.values("latest_api_info_id"),
            created_at__gt=value,
        ).values("video_id")

        return queryset.filter(Q(updated_at__gt=value) | Q(pk__in=videos_with_new_info))

    def filter_has_api_infos(
        self, queryset: QuerySet[TikTokVideo], name: str, value: bool
    ) -> QuerySet[TikTokVideo]:
        return queryset.filter(latest_api_info_id__isnull=not value)
