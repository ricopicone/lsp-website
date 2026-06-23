"""Seed the Applications Coordinator role (task #272).

Gates the analyst-availability console at /admin-tools/availability/. The
coordinator maintains which Analysts of the School are available for each LSP
function. Appoint the holder via Board → Appointments (or the Django admin).
"""

from __future__ import annotations

from django.db import migrations

KEY = "applications_coordinator"
NAME = "Applications Coordinator"
DESCRIPTION = (
    "Maintains the analyst-availability table: which Analysts of the School "
    "are available for Application Interviews, as an Advisor, for Control "
    "analysis, and for Personal analysis. Reminds analysts to keep it current."
)


def seed(apps, schema_editor):
    StaffRole = apps.get_model("core", "StaffRole")
    StaffRole.objects.get_or_create(
        key=KEY, defaults={"name": NAME, "description": DESCRIPTION},
    )


def unseed(apps, schema_editor):
    StaffRole = apps.get_model("core", "StaffRole")
    StaffRole.objects.filter(key=KEY).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0009_seed_referral_coordinator_role")]
    operations = [migrations.RunPython(seed, unseed)]
