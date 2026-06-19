from django.contrib import admin
from django.http import HttpRequest

from ddcs.metadata.models import (
    TikTokHashtag,
    TikTokMusic,
    TikTokUser,
    TikTokVideo,
)
from ddcs.metadata.research_api.models import (
    APIHashtagInfos,
    APIMusicInfos,
    APIUserInfos,
    APIUserStatistics,
    APIVideoInfos,
    APIVideoStatistics,
)


class ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request: HttpRequest, obj=None) -> bool:  # noqa: ANN001
        return False

    def get_readonly_fields(self, request: HttpRequest, obj=None) -> list[str]:  # noqa: ANN001
        return [f.name for f in self.model._meta.fields]  # noqa: SLF001


class APIVideoInfosInline(ReadOnlyInline):
    model = APIVideoInfos
    fields = (
        "created_at",
        "create_time",
        "description",
        "region_code",
        "duration",
        "is_stem_verified",
    )


class APIVideoStatisticsInline(ReadOnlyInline):
    model = APIVideoStatistics
    fields = (
        "created_at",
        "view_count",
        "like_count",
        "comment_count",
        "share_count",
        "favorites_count",
    )


class APIUserInfosInline(ReadOnlyInline):
    model = APIUserInfos
    fields = (
        "created_at",
        "name",
        "display_name",
        "is_verified",
        "is_private",
    )


class APIUserStatisticsInline(ReadOnlyInline):
    model = APIUserStatistics
    fields = (
        "created_at",
        "follower_count",
        "following_count",
        "video_count",
        "likes_count",
    )


class APIMusicInfosInline(ReadOnlyInline):
    model = APIMusicInfos
    fields = ("created_at", "name")


class APIHashtagInfosInline(ReadOnlyInline):
    model = APIHashtagInfos
    fields = ("created_at", "description")


@admin.register(TikTokVideo)
class TikTokVideoAdmin(admin.ModelAdmin):
    list_display = (
        "id_tiktok",
        "user",
        "inferred_create_time",
        "added_by",
        "created_at",
    )
    list_filter = ("added_by",)
    search_fields = ("id_tiktok", "user__name")
    autocomplete_fields = ("user", "music", "hashtags")
    readonly_fields = ("created_at", "updated_at", "inferred_create_time")
    inlines = (APIVideoInfosInline, APIVideoStatisticsInline)


@admin.register(TikTokUser)
class TikTokUserAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "id_tiktok",
        "monitor_api",
        "monitoring_priority_api",
        "api_last_monitored_at",
        "added_by",
    )
    list_filter = ("added_by", "monitor_api")
    search_fields = ("name", "id_tiktok")
    readonly_fields = ("created_at", "updated_at", "api_last_monitored_at")
    inlines = (APIUserInfosInline, APIUserStatisticsInline)


@admin.register(TikTokMusic)
class TikTokMusicAdmin(admin.ModelAdmin):
    list_display = ("id_tiktok", "added_by", "created_at")
    list_filter = ("added_by",)
    search_fields = ("id_tiktok",)
    readonly_fields = ("created_at", "updated_at")
    inlines = (APIMusicInfosInline,)


@admin.register(TikTokHashtag)
class TikTokHashtagAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "id_tiktok",
        "monitor_api",
        "monitoring_priority_api",
        "added_by",
    )
    list_filter = ("added_by", "monitor_api")
    search_fields = ("name", "id_tiktok")
    readonly_fields = ("created_at", "updated_at", "api_last_monitored_at")
    inlines = (APIHashtagInfosInline,)
