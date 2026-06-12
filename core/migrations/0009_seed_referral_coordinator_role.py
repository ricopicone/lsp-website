"""Seed the Referral Coordinator role (task #229).

Gates the referral workflow surface at /admin-tools/referrals/. Appoint the
holder via Board → Appointments (or the Django admin).
"""

from __future__ import annotations

from django.db import migrations

KEY = "referral_coordinator"
NAME = "Referral Coordinator"
DESCRIPTION = (
    "Runs the Find-an-Analyst referral process: tracks requests, distributes "
    "them to the referral list, and replies to requesters with available "
    "clinicians."
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
    dependencies = [("core", "0008_seed_assistant_developer_roles")]
    operations = [migrations.RunPython(seed, unseed)]
