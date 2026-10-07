import json
from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import authentication, permissions
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ddcs.metadata.scraper.serializers import (
    ClaimedScrapeTargetSerializer,
    ScrapeResultsEnvelopeSerializer,
    ScrapeResultSerializer,
    ScrapeResultsRequestSerializer,
    ScrapeResultsResponseSerializer,
    ScrapeTargetClaimRequestSerializer,
    ScrapeTargetClaimResponseSerializer,
)
from ddcs.metadata.scraper.service import (
    ExternalResultStatus,
    claim_targets,
    record_external_result,
)

SYNC_PERMISSION = "ddcs_metadata_scraper.sync_scrape_targets"


class CanSyncScrapeTargets(permissions.BasePermission):
    """Only accounts set up as external scrapers may work on the queue."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        return request.user.has_perm(SYNC_PERMISSION)


class ExternalScraperAPIView(APIView):
    authentication_classes = [authentication.TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, CanSyncScrapeTargets]


class ScrapeTargetClaimView(ExternalScraperAPIView):
    """
    Claim the next videos that are missing metadata, for scraping.

    * Requires token authentication and the permission
      "Can claim scrape targets and submit scraped results".
    * Returns the videos in queue order (most relevant first) and reserves
      them for the caller until `lease_expires_at`. Submit a result for each
      of them to the results endpoint; videos without one return to the
      queue when the lease runs out.
    * An empty `results` list means there is nothing to scrape right now.
    """

    @extend_schema(
        request=ScrapeTargetClaimRequestSerializer,
        responses=ScrapeTargetClaimResponseSerializer,
    )
    def post(self, request: Request) -> Response:
        serializer = ScrapeTargetClaimRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        targets, lease_expires_at = claim_targets(
            request.user,
            serializer.validated_data["limit"],
            serializer.validated_data["scraper_id"],
        )
        return Response(
            {
                "lease_expires_at": lease_expires_at,
                "results": ClaimedScrapeTargetSerializer(targets, many=True).data,
            }
        )


class ScrapeResultsView(ExternalScraperAPIView):
    """
    Submit what was scraped for previously claimed videos.

    * Requires token authentication and the permission
      "Can claim scrape targets and submit scraped results".
    * One entry per video, with an `outcome`:
      `success` (with the raw `data`, optionally a `caption`),
      `unavailable` (TikTok reports the video as gone or private),
      `failed` (anything else; the video is retried later) or
      `released` (not scraped, e.g. because TikTok blocked the scraper: the
      video returns to the queue without counting as an attempt).
    * Entries are handled independently. The response lists, in the same
      order, what became of each: `stored`, `recorded`, `released`,
      `already_done`, `not_claimed` or `invalid` (see `detail`).
    """

    @extend_schema(
        request=ScrapeResultsRequestSerializer,
        responses=ScrapeResultsResponseSerializer,
    )
    def post(self, request: Request) -> Response:
        envelope = ScrapeResultsEnvelopeSerializer(data=request.data)
        envelope.is_valid(raise_exception=True)
        return Response(
            {
                "results": [
                    self._record(request, item)
                    for item in envelope.validated_data["results"]
                ]
            }
        )

    @staticmethod
    def _record(request: Request, item: Any) -> dict[str, Any]:  # noqa: ANN401
        serializer = ScrapeResultSerializer(data=item)
        if not serializer.is_valid():
            id_tiktok = item.get("id_tiktok") if isinstance(item, dict) else None
            return {
                "id_tiktok": id_tiktok if isinstance(id_tiktok, int) else None,
                "status": ExternalResultStatus.INVALID,
                "detail": json.dumps(serializer.errors),
            }
        status, detail = record_external_result(request.user, serializer.validated_data)
        return {
            "id_tiktok": serializer.validated_data["id_tiktok"],
            "status": status,
            "detail": detail,
        }
