"""Seed the Registrar role (task #470).

A placeholder for a position the school hasn't created yet: it gates the
Registration Admin console at /admin-tools/registrations/. Left unheld until
the school appoints someone. Holders are never publicly badged.
"""

from __future__ import annotations

from django.db import migrations

KEY, NAME, DESCRIPTION = (
    "registrar", "Registrar",
    "Manages event registrations across the program: approvals, comps, and "
    "opening/closing registration. Not publicly listed.",
)


def seed(apps, schema_editor):
    StaffRole = apps.get_model("core", "StaffRole")
    StaffRole.objects.get_or_create(
        key=KEY, defaults={"name": NAME, "description": DESCRIPTION},
    )


def unseed(apps, schema_editor):
    apps.get_model("core", "StaffRole").objects.filter(key=KEY).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0012_seed_president_vice_president")]
    operations = [migrations.RunPython(seed, unseed)]
