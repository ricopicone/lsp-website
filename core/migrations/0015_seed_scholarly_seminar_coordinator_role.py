"""Seed the Scholarly Seminar Series Coordinator role (task #851).

Proposes the series' talks to the Program Committee and hosts them. Appointed
on Board → Appointments; holders are badged in the directory.
"""

from __future__ import annotations

from django.db import migrations

KEY, NAME, DESCRIPTION = (
    "scholarly_seminar_coordinator", "Scholarly Seminar Series Coordinator",
    "Coordinates the Scholarly Seminar Series: proposes its talks to the "
    "Program Committee and hosts them (the meeting room, the recording, the "
    "joining instructions).",
)


def seed(apps, schema_editor):
    StaffRole = apps.get_model("core", "StaffRole")
    StaffRole.objects.get_or_create(
        key=KEY, defaults={"name": NAME, "description": DESCRIPTION},
    )


def unseed(apps, schema_editor):
    apps.get_model("core", "StaffRole").objects.filter(key=KEY).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0014_seed_election_administrator_role")]
    operations = [migrations.RunPython(seed, unseed)]
