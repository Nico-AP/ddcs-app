from rest_framework import serializers

from ddcs.metadata.models import Keyword, TikTokHashtag, TikTokVideo
from ddcs.metadata.research_api.models import APIVideoInfos


class TikTokVideoSerializer(serializers.HyperlinkedModelSerializer):
    user = serializers.CharField(source="user.name", read_only=True, default=None)
    description = serializers.SerializerMethodField()
    create_time = serializers.SerializerMethodField()
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
        if api_info and api_info.created_at:
            create_time = api_info.created_at.isoformat()
        else:
            create_time = None
        return create_time

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
