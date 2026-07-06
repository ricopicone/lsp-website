"""Retire the Applications Coordinator StaffRole (task #272).

The Applications Coordinator is now an officer role on the Meeting of Analysts
workgroup (workgroups.WorkgroupMembership.Role.APPLICATIONS_COORDINATOR), so the
standalone StaffRole is removed. Reverse re-creates the (empty) row.
"""

from __future__ import annotations

from django.db import migrations

KEY = "applications_coordinator"


def remove(apps, schema_editor):
    StaffRole = apps.get_model("core", "StaffRole")
    StaffRole.objects.filter(key=KEY).delete()


def restore(apps, schema_editor):
    StaffRole = apps.get_model("core", "StaffRole")
    StaffRole.objects.get_or_create(
        key=KEY, defaults={"name": "Applications Coordinator"},
    )


class Migration(migrations.Migration):
    dependencies = [("core", "0010_seed_applications_coordinator_role")]
    operations = [migrations.RunPython(remove, restore)]
