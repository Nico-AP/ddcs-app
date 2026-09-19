from django.db import migrations, models


def _mark_existing_with_watches(apps, schema_editor) -> None:  # noqa: ANN001
    ParticipantReportStatistics = apps.get_model(
        "ddcs_reports", "ParticipantReportStatistics"
    )
    ParticipantReportStatistics.objects.filter(videos_seen_count_total__gt=0).update(
        has_watch_history=True
    )


class Migration(migrations.Migration):
    dependencies = [
        ("ddcs_reports", "0003_one_report_per_participant"),
    ]

    operations = [
        migrations.AddField(
            model_name="participantreportstatistics",
            name="has_watch_history",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(_mark_existing_with_watches, migrations.RunPython.noop),
    ]
