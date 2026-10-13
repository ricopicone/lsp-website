"""Seed the Election Administrator role (task #813).

Runs the Board election: sets its dates, keeps the voter roll, and counts the
votes. Appointed by the Board on Board → Appointments. Holders are never
publicly badged.
"""

from __future__ import annotations

from django.db import migrations

KEY, NAME, DESCRIPTION = (
    "election_administrator", "Election Administrator",
    "Runs the Board election: sets its dates, keeps the voter roll, and counts "
    "the votes. Should be neither a director nor a candidate. Not publicly "
    "listed.",
)


def seed(apps, schema_editor):
    StaffRole = apps.get_model("core", "StaffRole")
    StaffRole.objects.get_or_create(
        key=KEY, defaults={"name": NAME, "description": DESCRIPTION},
    )


def unseed(apps, schema_editor):
    apps.get_model("core", "StaffRole").objects.filter(key=KEY).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0013_seed_registrar_role")]
    operations = [migrations.RunPython(seed, unseed)]
