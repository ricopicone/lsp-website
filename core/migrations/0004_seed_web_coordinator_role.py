"""Seed the Web Coordinator staff role.

Holders are assigned in the admin; superusers implicitly hold every role, so
no holder needs to be seeded. Treasurer / Cartel Coordinator roles are added
when their panels arrive.
"""

from __future__ import annotations

from django.db import migrations


def seed(apps, schema_editor):
    StaffRole = apps.get_model("core", "StaffRole")
    StaffRole.objects.get_or_create(
        key="web_coordinator",
        defaults={
            "name": "Web Coordinator",
            "description": "Manages site content and configuration "
            "(footer aphorisms, and more over time).",
        },
    )


def unseed(apps, schema_editor):
    StaffRole = apps.get_model("core", "StaffRole")
    StaffRole.objects.filter(key="web_coordinator").delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0003_staffrole")]
    operations = [migrations.RunPython(seed, unseed)]
