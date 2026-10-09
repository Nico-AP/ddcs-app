from django.db.models import OuterRef, Prefetch, QuerySet, Subquery
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import authentication, generics, permissions
from rest_framework.pagination import CursorPagination

from ddcs.metadata.filters import PrioritisedTikTokVideoFilter, TikTokVideoFilter
from ddcs.metadata.models import TikTokVideo
from ddcs.metadata.priority import annotate_priority
from ddcs.metadata.research_api.models import APIVideoInfos
from ddcs.metadata.scraper.models import VideoInfosScraped
from ddcs.metadata.serializers import (
    PrioritisedTikTokVideoSerializer,
    TikTokVideoSerializer,
)


class TikTokVideoCursorPagination(CursorPagination):
    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 500
    ordering = "-pk"


class TikTokVideoList(generics.ListAPIView):
    """
    List all TikTok videos with metadata.

    * Requires token authentication.
    * Responses can be filtered by: id_tiktok, usernames, create_date_from/to,
      keywords, monitored_users (bool), region_codes, has_api_infos (bool),
      has_classifications (bool), updated_since.
    """

    authentication_classes = [authentication.TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TikTokVideoSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = TikTokVideoFilter
    pagination_class = TikTokVideoCursorPagination

    def get_queryset(self) -> QuerySet[TikTokVideo]:
        # Computed once here; TikTokVideoFilter's methods reuse this
        # annotation instead of each re-deriving their own "latest row"
        # subquery.
        latest_info = APIVideoInfos.objects.filter(video=OuterRef("pk")).order_by(
            "-created_at"
        )
        return (
            TikTokVideo.objects.annotate(
                latest_api_info_id=Subquery(latest_info.values("pk")[:1]),
                latest_create_time=Subquery(latest_info.values("create_time")[:1]),
                latest_region_code=Subquery(latest_info.values("region_code")[:1]),
            )
            .prefetch_related(
                Prefetch(
                    "api_infos",
                    queryset=APIVideoInfos.objects.order_by("-created_at"),
                    to_attr="latest_api_info_list",
                )
            )
            .distinct()
        )


class PrioritisedTikTokVideoList(generics.ListAPIView):
    """
    List all TikTok videos with a priority and their metadata, whichever
    source it comes from.

    * Requires token authentication.
    * `priority` (higher = more important):
      4 = watched by a donor (at any time) and delivered by the Research API;
      3 = watched by a donor within the study period, no Research API data;
      2 = delivered by the Research API, in no donation;
      1 = everything else.
    * `metadata_source` says where the metadata fields come from:
      `research_api`, `scraped`, or null if the video has no metadata yet
      (the metadata fields are then null or empty). Research API data takes
      precedence; `region_code`, `is_stem_verified` and `video_label` are
      null for scraped videos.
    * `last_seen_at` is the most recent view of the video in any donation
      (null if it is in none).
    * Takes the filters of the video list, plus: priority (one or several,
      comma-separated), metadata_source, has_metadata (bool). `updated_since`
      reports every video whose priority, `last_seen_at` or metadata changed
      since then.
    """

    authentication_classes = [authentication.TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PrioritisedTikTokVideoSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = PrioritisedTikTokVideoFilter
    pagination_class = TikTokVideoCursorPagination

    def get_queryset(self) -> QuerySet[TikTokVideo]:
        # What TikTokVideoFilter relies on. As aliases, so that the
        # subqueries only run when a filter uses them, not for every row of
        # every page.
        latest_info = APIVideoInfos.objects.filter(video=OuterRef("pk")).order_by(
            "-created_at"
        )
        queryset = TikTokVideo.objects.alias(
            latest_api_info_id=Subquery(latest_info.values("pk")[:1]),
            latest_create_time=Subquery(latest_info.values("create_time")[:1]),
            latest_region_code=Subquery(latest_info.values("region_code")[:1]),
        )
        return (
            annotate_priority(queryset)
            .select_related("donation_infos", "user", "music")
            .prefetch_related(
                "hashtags",
                "keywords",
                Prefetch(
                    "api_infos",
                    queryset=APIVideoInfos.objects.order_by("-created_at"),
                    to_attr="latest_api_info_list",
                ),
                Prefetch(
                    "scraped_infos",
                    # The page payload and the caption file are large and
                    # not served here.
                    queryset=VideoInfosScraped.objects.defer(
                        "raw", "caption_vtt"
                    ).order_by("-created_at"),
                    to_attr="latest_scraped_info_list",
                ),
            )
        )
