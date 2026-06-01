"""Seed the Treasurer role so it can have holders managed in the admin.

Django staff keep treasurer access (back-compat); this lets a non-staff member
be made Treasurer by holding the role.
"""

from __future__ import annotations

from django.db import migrations


def seed(apps, schema_editor):
    StaffRole = apps.get_model("core", "StaffRole")
    StaffRole.objects.get_or_create(
        key="treasurer",
        defaults={
            "name": "Treasurer",
            "description": "Dues and tuition dashboards, member ledgers, and exports.",
        },
    )


def unseed(apps, schema_editor):
    StaffRole = apps.get_model("core", "StaffRole")
    StaffRole.objects.filter(key="treasurer").delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0005_seed_lsp_and_cartel_roles")]
    operations = [migrations.RunPython(seed, unseed)]
