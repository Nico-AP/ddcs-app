from datetime import UTC
from typing import Any

from rest_framework import serializers

from ddcs.metadata.scraper.models import VideoInfosScraped
from ddcs.metadata.scraper.service import ExternalOutcome, ExternalResultStatus

MAX_CLAIM_LIMIT = 500
# A result carries a whole itemStruct and possibly a caption file, so
# requests get large quickly.
MAX_RESULTS_PER_REQUEST = 50

_CaptionStatus = VideoInfosScraped.CaptionStatus


class ScrapeTargetClaimRequestSerializer(serializers.Serializer):
    limit = serializers.IntegerField(
        min_value=1,
        max_value=MAX_CLAIM_LIMIT,
        default=100,
        help_text="Maximum number of videos to claim.",
    )
    scraper_id = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        default="",
        help_text=(
            "Free-text name of the scraper instance (e.g. its host). Stored "
            "with the claimed targets for information."
        ),
    )


class ClaimedScrapeTargetSerializer(serializers.Serializer):
    id_tiktok = serializers.IntegerField(source="video.id_tiktok")
    occurrence_count = serializers.IntegerField()
    last_watched_at = serializers.DateTimeField(allow_null=True, default_timezone=UTC)


class ScrapeTargetClaimResponseSerializer(serializers.Serializer):
    lease_expires_at = serializers.DateTimeField(
        help_text="Videos no result was submitted for by then return to the queue."
    )
    results = ClaimedScrapeTargetSerializer(many=True)


class ScrapedCaptionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=[
            _CaptionStatus.FETCHED,
            _CaptionStatus.NONE_AVAILABLE,
            _CaptionStatus.FAILED,
        ]
    )
    vtt = serializers.CharField(
        required=False,
        trim_whitespace=False,
        help_text="The original-language WebVTT file as downloaded.",
    )
    language = serializers.CharField(
        required=False, allow_blank=True, max_length=32, help_text='E.g. "deu-DE".'
    )
    is_auto_generated = serializers.BooleanField(required=False, allow_null=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["status"] == _CaptionStatus.FETCHED and not attrs.get("vtt"):
            raise serializers.ValidationError(
                {"vtt": "Required when status is 'fetched'."}
            )
        return attrs


class ScrapeResultSerializer(serializers.Serializer):
    id_tiktok = serializers.IntegerField()
    outcome = serializers.ChoiceField(choices=ExternalOutcome.choices)
    data = serializers.DictField(
        required=False,
        help_text=(
            "Outcome 'success': the video's raw itemStruct from the page's "
            "rehydration data (__DEFAULT_SCOPE__ > webapp.video-detail > "
            "itemInfo > itemStruct)."
        ),
    )
    caption = ScrapedCaptionSerializer(
        required=False,
        allow_null=True,
        help_text="Outcome 'success': omit if captions were not collected.",
    )
    tiktok_status_code = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Outcome 'unavailable': statusCode TikTok returned.",
    )
    error_type = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
        help_text="Outcome 'failed': short name of the error.",
    )
    error_msg = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["outcome"] == ExternalOutcome.SUCCESS and not attrs.get("data"):
            raise serializers.ValidationError(
                {"data": "Required when outcome is 'success'."}
            )
        return attrs


class ScrapeResultsRequestSerializer(serializers.Serializer):
    """Documents the request; the view validates each result on its own."""

    results = ScrapeResultSerializer(
        many=True, min_length=1, max_length=MAX_RESULTS_PER_REQUEST
    )


class ScrapeResultsEnvelopeSerializer(serializers.Serializer):
    results = serializers.ListField(
        child=serializers.JSONField(),
        min_length=1,
        max_length=MAX_RESULTS_PER_REQUEST,
    )


class ScrapeResultStatusSerializer(serializers.Serializer):
    id_tiktok = serializers.IntegerField(allow_null=True)
    status = serializers.ChoiceField(choices=ExternalResultStatus.choices)
    detail = serializers.CharField(allow_blank=True)


class ScrapeResultsResponseSerializer(serializers.Serializer):
    results = ScrapeResultStatusSerializer(many=True)
