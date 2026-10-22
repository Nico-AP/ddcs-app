from typing import Any

from django.conf import settings
from django.db import OperationalError, connection
from django.db.models import OuterRef, Prefetch, QuerySet, Subquery
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import authentication, generics, permissions, status
from rest_framework.exceptions import APIException
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.response import Response

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


# SQLSTATE PostgreSQL reports for a statement cancelled by statement_timeout.
_QUERY_CANCELED = "57014"


class QueryTimedOut(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = (
        "The request took too long to answer and was cancelled. Narrow it down "
        "(e.g. by id_tiktok), or fetch the list without filters and filter "
        "the results yourself."
    )
    default_code = "query_timed_out"


class StatementTimeoutMixin:
    """Cancels database statements of a list request that run too long.

    A filter that matches few videos can make a page scan a large part of
    the table. Without a limit such a statement keeps running in the
    database after the web server has given up on the request, and retries
    pile up. The limit (``METADATA_API_STATEMENT_TIMEOUT_MS``) applies to
    each statement of the request; a cancelled one is answered with 503.
    PostgreSQL only.
    """

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:  # noqa: ANN401
        self._limit_statement_time()
        try:
            return super().list(request, *args, **kwargs)
        except OperationalError as e:
            if getattr(e.__cause__, "sqlstate", None) == _QUERY_CANCELED:
                raise QueryTimedOut from e
            raise

    @staticmethod
    def _limit_statement_time() -> None:
        timeout_ms = settings.METADATA_API_STATEMENT_TIMEOUT_MS
        if not timeout_ms or connection.vendor != "postgresql":
            return
        # Local (third argument): until the end of the transaction, which is
        # the request (ATOMIC_REQUESTS). Without one it would have no effect.
        # set_config() rather than SET, which takes no bound parameters and
        # so fails when the driver binds them on the server.
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                [str(int(timeout_ms))],
            )


class TikTokVideoList(StatementTimeoutMixin, generics.ListAPIView):
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


class PrioritisedTikTokVideoList(StatementTimeoutMixin, generics.ListAPIView):
    """
    List all TikTok videos with a priority and their metadata, whichever
    source it comes from.

    * Requires token authentication.
    * `priority` (higher = more important):
      4 = watched, liked or bookmarked by a donor (at any time) or listed in
      Datapods, and delivered by the Research API;
      3 = watched, liked or bookmarked by a donor within the study period or
      listed in Datapods, no Research API data;
      2 = delivered by the Research API, in no donation and not listed in
      Datapods;
      1 = everything else.
    * `metadata_source` says where the metadata fields come from:
      `research_api`, `scraped`, or null if the video has no metadata yet
      (the metadata fields are then null or empty). Research API data takes
      precedence; `is_stem_verified` and `video_label` are null for scraped
      videos.
    * `last_interaction_at` is the most recent view, like or bookmark of the
      video in any donation (null if it is in none).
    * `in_datapods` is true for videos listed in Datapods, whether or not a
      donation shows them too (`last_interaction_at` tells).
    * Takes the filters of the video list except region_codes and
      has_api_infos, plus: priority (one or several, comma-separated),
      metadata_source, has_metadata (bool). The create_date filters look at
      Research API data only. `updated_since`
      reports every video whose priority, `last_interaction_at` or metadata
      changed since then.
    """

    authentication_classes = [authentication.TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PrioritisedTikTokVideoSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = PrioritisedTikTokVideoFilter
    pagination_class = TikTokVideoCursorPagination

    def get_queryset(self) -> QuerySet[TikTokVideo]:
        # What the create_date filters rely on. As an alias, so that the
        # subquery only runs when one of them is used, not for every row of
        # every page.
        latest_info = APIVideoInfos.objects.filter(video=OuterRef("pk")).order_by(
            "-created_at"
        )
        queryset = TikTokVideo.objects.alias(
            latest_create_time=Subquery(latest_info.values("create_time")[:1]),
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
