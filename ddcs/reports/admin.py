from django.contrib import admin

from ddcs.reports.models import ParticipantReportStatistics


@admin.register(ParticipantReportStatistics)
class ParticipantReportStatisticsAdmin(admin.ModelAdmin):
    list_display = ("id", "participant", "generated_at", "videos_seen_count_total")
    readonly_fields = ("generated_at",)
