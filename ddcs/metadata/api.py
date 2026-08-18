from django.db.models import OuterRef, Prefetch, QuerySet, Subquery
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import authentication, generics, permissions
from rest_framework.pagination import CursorPagination

from ddcs.metadata.filters import TikTokVideoFilter
from ddcs.metadata.models import TikTokVideo
from ddcs.metadata.research_api.models import APIVideoInfos
from ddcs.metadata.serializers import TikTokVideoSerializer


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
