"""Rename the "Programming Committee" to "Program Committee".

The Wix site (and the committee itself) uses "Program Committee" — the
original seed used "Programming" by mistake. Idempotent and slug-stable
(the slug stays ``programming-committee`` so existing references via
slug — the ROSTER placeholder in content/pages/about.md, the
seed_committees management command — keep working).
"""

from django.db import migrations


def rename(apps, schema_editor):
    Committee = apps.get_model("committees", "Committee")
    Committee.objects.filter(slug="programming-committee").update(
        name="Program Committee",
        description=(
            "Reviews proposals, schedules the curriculum, and supports key "
            "School events such as the Work Day of the School and the Days "
            "of Assembly."
        ),
    )


def rollback(apps, schema_editor):
    Committee = apps.get_model("committees", "Committee")
    Committee.objects.filter(slug="programming-committee").update(
        name="Programming Committee",
        description=(
            "Runs seminars and special events; primary internal customer of "
            "the registration system."
        ),
    )


class Migration(migrations.Migration):
    dependencies = [("committees", "0002_seed_committees")]
    operations = [migrations.RunPython(rename, rollback)]
