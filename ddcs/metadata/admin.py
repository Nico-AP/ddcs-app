from django import forms
from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest
from import_export.admin import ExportMixin
from import_export.forms import ExportForm
from import_export.resources import ModelResource

from ddcs.metadata.models import (
    DataOrigins,
    ResearchAPIQueryTracker,
    SyncAttempt,
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


class TikTokVideoResource(ModelResource):
    """Resource used to enable export through admin."""

    class Meta:
        model = TikTokVideo

    def filter_export(self, queryset: QuerySet, **kwargs) -> QuerySet:
        qs = super().filter_export(queryset, **kwargs)
        export_form = kwargs.get("export_form")
        if not export_form:
            return qs

        data_source = export_form.cleaned_data.get("data_source")
        if data_source:
            qs = qs.filter(added_by=data_source)

        limit = export_form.cleaned_data.get("limit_to_last")
        if limit:
            qs = qs.order_by("-created_at")[:limit]

        return qs


class TikTokVideoExportForm(ExportForm):
    limit_to_last = forms.IntegerField(
        required=False,
        initial=1000,
        min_value=1,
        label="Limit to last N entries (leave blank for all)",
    )
    data_source = forms.ChoiceField(
        required=False,
        choices=[("", "All sources"), *DataOrigins.choices],
        label="Data source",
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


class SyncAttemptUserInline(ReadOnlyInline):
    model = SyncAttempt
    fk_name = "user"
    fields = (
        "target_date",
        "attempted_at",
        "status",
        "tracker",
    )


class APIMusicInfosInline(ReadOnlyInline):
    model = APIMusicInfos
    fields = ("created_at", "name")


class APIHashtagInfosInline(ReadOnlyInline):
    model = APIHashtagInfos
    fields = ("created_at", "description")


@admin.register(TikTokVideo)
class TikTokVideoAdmin(ExportMixin, admin.ModelAdmin):
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
    resource_classes = [TikTokVideoResource]
    export_form_class = TikTokVideoExportForm


@admin.register(TikTokUser)
class TikTokUserAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "id_tiktok",
        "monitor_api",
        "monitoring_priority_api",
        "added_by",
    )
    list_filter = ("added_by", "monitor_api")
    search_fields = ("name", "id_tiktok")
    readonly_fields = ("created_at", "updated_at")
    inlines = (APIUserInfosInline, APIUserStatisticsInline, SyncAttemptUserInline)


@admin.register(TikTokMusic)
class TikTokMusicAdmin(admin.ModelAdmin):
    list_display = ("id_tiktok", "added_by", "created_at")
    list_filter = ("added_by",)
    search_fields = ("id_tiktok",)
    readonly_fields = ("created_at", "updated_at")
    inlines = (APIMusicInfosInline,)


class SyncAttemptHashtagInline(ReadOnlyInline):
    model = SyncAttempt
    fk_name = "hashtag"
    fields = (
        "target_date",
        "attempted_at",
        "status",
        "tracker",
    )


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
    readonly_fields = ("created_at", "updated_at")
    inlines = (APIHashtagInfosInline, SyncAttemptHashtagInline)


class TrackerOriginFilter(admin.SimpleListFilter):
    """Whether the tracker's run came from a scheduled daily task or the backfill."""

    title = "origin"
    parameter_name = "origin"

    def lookups(self, request: HttpRequest, model_admin) -> list[tuple[str, str]]:  # noqa: ANN001
        return [("daily", "Daily"), ("backfill", "Backfill")]

    def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
        value = self.value()
        if value in {"daily", "backfill"}:
            return queryset.filter(query_parameters__origin=value)
        return queryset


@admin.register(ResearchAPIQueryTracker)
class ResearchAPIQueryTrackerAdmin(admin.ModelAdmin):
    list_display = (
        "start_time",
        "end_time",
        "query_function",
        "origin",
        "query_parameters",
        "query_result",
        "query_status",
    )
    list_filter = ("query_function", "query_status", TrackerOriginFilter)

    @admin.display(description="Origin")
    def origin(self, obj: ResearchAPIQueryTracker) -> str:
        return (obj.query_parameters or {}).get("origin", "—")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj=None) -> bool:  # noqa: ANN001
        return False

    def get_readonly_fields(self, request: HttpRequest, obj=None) -> bool:  # noqa: ANN001
        return [field.name for field in self.model._meta.fields]  # noqa: SLF001


class SyncAttemptKindFilter(admin.SimpleListFilter):
    """Which of the two possible targets (user vs keyword) the attempt is for."""

    title = "target kind"
    parameter_name = "kind"

    def lookups(self, request: HttpRequest, model_admin) -> list[tuple[str, str]]:  # noqa: ANN001
        return [("user", "User"), ("keyword", "Keyword")]

    def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
        if self.value() == "user":
            return queryset.filter(user__isnull=False)
        if self.value() == "keyword":
            return queryset.filter(hashtag__isnull=False)
        return queryset


class SyncAttemptSuccessFilter(admin.SimpleListFilter):
    """One-click filter for success vs any failure — the common diagnostic axis."""

    title = "outcome"
    parameter_name = "outcome"

    def lookups(self, request: HttpRequest, model_admin) -> list[tuple[str, str]]:  # noqa: ANN001
        return [("success", "Success"), ("failure", "Any failure")]

    def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
        if self.value() == "success":
            return queryset.filter(status=SyncAttempt.Status.SUCCESS)
        if self.value() == "failure":
            return queryset.exclude(status=SyncAttempt.Status.SUCCESS)
        return queryset


@admin.register(SyncAttempt)
class SyncAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "target_date",
        "attempted_at",
        "target",
        "status",
        "error_type",
        "tracker",
    )
    list_filter = (
        SyncAttemptSuccessFilter,
        "status",
        SyncAttemptKindFilter,
    )
    date_hierarchy = "target_date"
    search_fields = ("user__name", "hashtag__name")
    ordering = ("-attempted_at",)
    list_select_related = ("user", "hashtag", "tracker")

    @admin.display(description="Target", ordering="user__name")
    def target(self, obj: SyncAttempt) -> str:
        return str(obj.user or obj.hashtag)

    @admin.display(description="Error type")
    def error_type(self, obj: SyncAttempt) -> str:
        if not obj.error_details:
            return ""
        return obj.error_details.get("type", "")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj=None) -> bool:  # noqa: ANN001
        return False

    def get_readonly_fields(self, request: HttpRequest, obj=None) -> list[str]:  # noqa: ANN001
        return [field.name for field in self.model._meta.fields]  # noqa: SLF001
