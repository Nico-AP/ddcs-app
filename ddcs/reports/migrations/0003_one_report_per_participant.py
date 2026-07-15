import django.db.models.deletion
from django.db import migrations, models


def _keep_latest_report_per_participant(apps, schema_editor) -> None:  # noqa: ANN001
    """Delete all but the most recently generated report per participant.

    Needed before the participant field can become unique/one-to-one: any
    participant with more than one row (e.g. from a retried task run before
    report generation was made idempotent) would otherwise fail the migration.
    """
    ParticipantReportStatistics = apps.get_model(
        "ddcs_reports", "ParticipantReportStatistics"
    )
    seen_participant_ids = set()
    for stats in ParticipantReportStatistics.objects.order_by(
        "participant_id", "-generated_at"
    ):
        if stats.participant_id in seen_participant_ids:
            stats.delete()
        else:
            seen_participant_ids.add(stats.participant_id)


class Migration(migrations.Migration):
    dependencies = [
        ("ddcs_reports", "0002_behaviour_comparisons"),
        ("ddm_participation", "0002_alter_participant_project"),
    ]

    operations = [
        migrations.RunPython(
            _keep_latest_report_per_participant, migrations.RunPython.noop
        ),
        migrations.RemoveIndex(
            model_name="participantreportstatistics",
            name="ddcs_report_partici_825666_idx",
        ),
        migrations.AlterField(
            model_name="participantreportstatistics",
            name="participant",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                to="ddm_participation.participant",
            ),
        ),
    ]
