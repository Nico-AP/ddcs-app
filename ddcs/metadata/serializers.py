from datetime import UTC
from typing import Any

from rest_framework import serializers

from ddcs.metadata.models import Keyword, TikTokHashtag, TikTokVideo
from ddcs.metadata.priority import MetadataSource
from ddcs.metadata.research_api.models import APIVideoInfos
from ddcs.metadata.scraper.models import VideoInfosScraped


class TikTokVideoSerializer(serializers.HyperlinkedModelSerializer):
    user = serializers.CharField(source="user.name", read_only=True, default=None)
    description = serializers.SerializerMethodField()
    create_time = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()
    region_code = serializers.SerializerMethodField()
    duration = serializers.SerializerMethodField()
    voice_to_text = serializers.SerializerMethodField()
    is_stem_verified = serializers.SerializerMethodField()
    video_mention_list = serializers.SerializerMethodField()
    effect_list = serializers.SerializerMethodField()
    video_label = serializers.SerializerMethodField()

    music = serializers.BigIntegerField(
        source="music.id_tiktok", read_only=True, default=None
    )
    hashtags = serializers.SlugRelatedField(
        many=True, slug_field="name", queryset=TikTokHashtag.objects.all()
    )
    keywords = serializers.SlugRelatedField(
        many=True, slug_field="name", queryset=Keyword.objects.all()
    )

    _cached_latest_api_info: APIVideoInfos | None = None
    latest_api_info_list: list[APIVideoInfos] | None = None

    class Meta:
        model = TikTokVideo
        fields = [
            "id_tiktok",
            "user",
            "description",
            "create_time",
            "created_at",
            "region_code",
            "duration",
            "voice_to_text",
            "is_stem_verified",
            "video_mention_list",
            "effect_list",
            "video_label",
            "music",
            "hashtags",
            "keywords",
        ]

    @staticmethod
    def _get_latest_api_info(obj: TikTokVideo) -> APIVideoInfos | None:
        # 1. Look for view-level prefetch list first
        if hasattr(obj, "latest_api_info_list"):
            return obj.latest_api_info_list[0] if obj.latest_api_info_list else None

        # 2. Fallback: Query DB once per instance and cache it dynamically
        if not hasattr(obj, "_cached_latest_api_info"):
            obj._cached_latest_api_info = obj.api_infos.order_by("-created_at").first()  # noqa: SLF001

        return obj._cached_latest_api_info  # noqa: SLF001

    def get_description(self, obj: TikTokVideo) -> str | None:
        api_info = self._get_latest_api_info(obj)
        return api_info.description if api_info else None

    def get_create_time(self, obj: TikTokVideo) -> str | None:
        api_info = self._get_latest_api_info(obj)
        if api_info and api_info.create_time:
            create_time = api_info.create_time.isoformat()
        else:
            create_time = None
        return create_time

    def get_created_at(self, obj: TikTokVideo) -> str | None:
        api_info = self._get_latest_api_info(obj)
        if api_info and api_info.created_at:
            created_at = api_info.created_at.isoformat()
        else:
            created_at = None
        return created_at

    def get_region_code(self, obj: TikTokVideo) -> str | None:
        api_info = self._get_latest_api_info(obj)
        return api_info.region_code if api_info else None

    def get_duration(self, obj: TikTokVideo) -> int | None:
        api_info = self._get_latest_api_info(obj)
        return api_info.duration if api_info else None

    def get_voice_to_text(self, obj: TikTokVideo) -> str | None:
        api_info = self._get_latest_api_info(obj)
        return api_info.voice_to_text if api_info else None

    def get_is_stem_verified(self, obj: TikTokVideo) -> bool | None:
        api_info = self._get_latest_api_info(obj)
        return api_info.is_stem_verified if api_info else None

    def get_video_mention_list(self, obj: TikTokVideo) -> list | None:
        api_info = self._get_latest_api_info(obj)
        return api_info.video_mention_list if api_info else None

    def get_video_label(self, obj: TikTokVideo) -> dict | None:
        api_info = self._get_latest_api_info(obj)
        return api_info.video_label if api_info else None

    def get_effect_list(self, obj: TikTokVideo) -> list | None:
        api_info = self._get_latest_api_info(obj)
        return api_info.effect_list if api_info else None


class PrioritisedTikTokVideoSerializer(serializers.ModelSerializer):
    """A video with its priority and the metadata of whichever source has it.

    The metadata fields are read from the latest Research API infos, or
    from the latest scraped infos if the video has none; both models name
    and format the shared fields alike. Expects the queryset of
    ``PrioritisedTikTokVideoList`` (``priority`` annotation, prefetched
    infos).
    """

    priority = serializers.IntegerField(read_only=True)
    metadata_source = serializers.SerializerMethodField()
    last_interaction_at = serializers.DateTimeField(
        source="donation_infos.last_interaction_at",
        read_only=True,
        default=None,
        default_timezone=UTC,
    )

    user = serializers.CharField(source="user.name", read_only=True, default=None)
    description = serializers.SerializerMethodField()
    create_time = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()
    region_code = serializers.SerializerMethodField()
    duration = serializers.SerializerMethodField()
    voice_to_text = serializers.SerializerMethodField()
    is_stem_verified = serializers.SerializerMethodField()
    video_mention_list = serializers.SerializerMethodField()
    effect_list = serializers.SerializerMethodField()
    video_label = serializers.SerializerMethodField()

    music = serializers.BigIntegerField(
        source="music.id_tiktok", read_only=True, default=None
    )
    hashtags = serializers.SlugRelatedField(
        many=True, slug_field="name", read_only=True
    )
    keywords = serializers.SlugRelatedField(
        many=True, slug_field="name", read_only=True
    )

    class Meta:
        model = TikTokVideo
        fields = [
            "id_tiktok",
            "priority",
            "metadata_source",
            "last_interaction_at",
            "user",
            "description",
            "create_time",
            "created_at",
            "region_code",
            "duration",
            "voice_to_text",
            "is_stem_verified",
            "video_mention_list",
            "effect_list",
            "video_label",
            "music",
            "hashtags",
            "keywords",
        ]

    @staticmethod
    def _get_infos(obj: TikTokVideo) -> APIVideoInfos | VideoInfosScraped | None:
        if obj.latest_api_info_list:
            return obj.latest_api_info_list[0]
        if obj.latest_scraped_info_list:
            return obj.latest_scraped_info_list[0]
        return None

    def _get_value(self, obj: TikTokVideo, field: str) -> Any:  # noqa: ANN401
        # Fields only the Research API provides are missing on scraped infos.
        return getattr(self._get_infos(obj), field, None)

    def get_metadata_source(self, obj: TikTokVideo) -> str | None:
        infos = self._get_infos(obj)
        if infos is None:
            return None
        if isinstance(infos, APIVideoInfos):
            return MetadataSource.RESEARCH_API.value
        return MetadataSource.SCRAPED.value

    def get_description(self, obj: TikTokVideo) -> str | None:
        return self._get_value(obj, "description")

    def get_create_time(self, obj: TikTokVideo) -> str | None:
        create_time = self._get_value(obj, "create_time")
        return create_time.isoformat() if create_time else None

    def get_created_at(self, obj: TikTokVideo) -> str | None:
        created_at = self._get_value(obj, "created_at")
        return created_at.isoformat() if created_at else None

    def get_region_code(self, obj: TikTokVideo) -> str | None:
        return self._get_value(obj, "region_code")

    def get_duration(self, obj: TikTokVideo) -> int | None:
        return self._get_value(obj, "duration")

    def get_voice_to_text(self, obj: TikTokVideo) -> str | None:
        return self._get_value(obj, "voice_to_text")

    def get_is_stem_verified(self, obj: TikTokVideo) -> bool | None:
        return self._get_value(obj, "is_stem_verified")

    def get_video_mention_list(self, obj: TikTokVideo) -> list | None:
        return self._get_value(obj, "video_mention_list")

    def get_effect_list(self, obj: TikTokVideo) -> list | None:
        return self._get_value(obj, "effect_list")

    def get_video_label(self, obj: TikTokVideo) -> dict | None:
        return self._get_value(obj, "video_label")
