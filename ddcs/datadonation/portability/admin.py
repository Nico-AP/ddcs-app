from django.contrib import admin

from ddcs.datadonation.portability.models import TikTokConnection, TikTokDataRequest


@admin.register(TikTokConnection)
class TikTokConnectionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "token_type", "scope")
    list_filter = ("scope",)


@admin.register(TikTokDataRequest)
class TikTokDataRequestAdmin(admin.ModelAdmin):
    list_display = ("connection", "issued_at", "last_polled", "status")
    list_filter = ("status",)
