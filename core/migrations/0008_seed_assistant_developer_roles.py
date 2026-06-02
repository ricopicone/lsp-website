"""Seed the Administrative Assistant to the Board and Web Developer roles.

Each gets its own admin page under /admin-tools/. Holders are managed in the
Django admin (or by a superuser, who implicitly holds every role).
"""

from __future__ import annotations

from django.db import migrations

ROLES = [
    (
        "admin_assistant",
        "Administrative Assistant to the Board",
        "Supports the Board: membership records, communications, and scheduling.",
    ),
    (
        "web_developer",
        "Web Developer",
        "Technical operations: the Django back office, deploys, and site internals.",
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
    dependencies = [("core", "0007_impersonationlog")]
    operations = [migrations.RunPython(seed, unseed)]
