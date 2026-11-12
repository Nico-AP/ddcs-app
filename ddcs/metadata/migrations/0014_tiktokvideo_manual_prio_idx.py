"""Partial index for the manual-priority filter of the prioritised video API.

On PostgreSQL the index is built with CREATE INDEX CONCURRENTLY, so writes to
the (large) video table are not blocked while it is built. That cannot run
inside a transaction, hence ``atomic = False``. Other databases (SQLite in
development and CI) build it the plain way. ``django.contrib.postgres`` is
not imported, as psycopg is not installed there.
"""

from django.db import migrations, models

INDEX = models.Index(
    fields=["manual_priority", "-id"],
    condition=models.Q(manual_priority__isnull=False),
    name="tiktokvideo_manual_prio_idx",
)


def _concurrently(schema_editor) -> dict:
    if schema_editor.connection.vendor == "postgresql":
        return {"concurrently": True}
    return {}


def add_index(apps, schema_editor):
    model = apps.get_model("ddcs_metadata", "TikTokVideo")
    schema_editor.add_index(model, INDEX, **_concurrently(schema_editor))


def remove_index(apps, schema_editor):
    model = apps.get_model("ddcs_metadata", "TikTokVideo")
    schema_editor.remove_index(model, INDEX, **_concurrently(schema_editor))


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("ddcs_metadata", "0013_tiktokvideo_manual_priority"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(model_name="tiktokvideo", index=INDEX),
            ],
            database_operations=[
                migrations.RunPython(add_index, remove_index),
            ],
        ),
    ]
