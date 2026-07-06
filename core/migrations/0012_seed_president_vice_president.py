"""Seed the President and Vice-President roles (task #272).

School officers: one appointment governs the Board and the Meeting of Analysts
both. Appoint holders via Board → Appointments. The Vice-President's display
``name`` may be edited (e.g. to "Co-President") without changing the ``key``.
"""

from __future__ import annotations

from django.db import migrations

ROLES = [
    (
        "president", "President",
        "President of the school. Governs the Board of Directors and the "
        "Meeting of Analysts.",
    ),
    (
        "vice_president", "Vice-President",
        "Vice-President of the school (sometimes styled “Co-President” — same "
        "role). Governs the Board of Directors and the Meeting of Analysts.",
    ),
]


def seed(apps, schema_editor):
    StaffRole = apps.get_model("core", "StaffRole")
    for key, name, description in ROLES:
        StaffRole.objects.get_or_create(
            key=key, defaults={"name": name, "description": description},
        )


def unseed(apps, schema_editor):
    StaffRole = apps.get_model("core", "StaffRole")
    StaffRole.objects.filter(key__in=[r[0] for r in ROLES]).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0011_retire_applications_coordinator_staffrole")]
    operations = [migrations.RunPython(seed, unseed)]
