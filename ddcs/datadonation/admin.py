from ddm.participation.models import Participant
from django.contrib import admin


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = (
        "external_id",
        "start_time",
        "end_time",
        "completed",
        "current_step",
    )
    list_filter = ("current_step",)
