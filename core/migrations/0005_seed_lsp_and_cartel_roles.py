"""Seed the LSP Staff and Cartel Coordinator roles.

These unify the former ``Profile.is_lsp_staff`` / ``Profile.is_cartel_coordinator``
booleans onto ``StaffRole``. The accounts data migration that follows copies
existing holders across before those columns are dropped.
"""

from __future__ import annotations

from django.db import migrations

ROLES = [
    ("lsp_staff", "LSP Staff",
     "Board entry, event-edit rights, and the Staff Parlêtre channel."),
    ("cartel_coordinator", "Cartel Coordinator",
     "Reviews and approves cartel proposals (CART-4)."),
]


def seed(apps, schema_editor):
    StaffRole = apps.get_model("core", "StaffRole")
    for key, name, description in ROLES:
        StaffRole.objects.get_or_create(
            key=key, defaults={"name": name, "description": description},
        )


def unseed(apps, schema_editor):
    StaffRole = apps.get_model("core", "StaffRole")
    StaffRole.objects.filter(key__in=[k for k, _, _ in ROLES]).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0004_seed_web_coordinator_role")]
    operations = [migrations.RunPython(seed, unseed)]
