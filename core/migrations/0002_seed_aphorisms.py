"""Seed the Aphorism table from the curated ``core.aphorisms.APHORISMS`` list.

One-time baseline; after this the table is the source of truth (editable via
the admin / Web Coordinator panel).
"""

from __future__ import annotations

from django.db import migrations


def seed(apps, schema_editor):
    Aphorism = apps.get_model("core", "Aphorism")
    if Aphorism.objects.exists():
        return
    from core.aphorisms import APHORISMS

    Aphorism.objects.bulk_create(
        [
            Aphorism(
                quote=a["quote"],
                short_attribution=a.get("short_attribution", ""),
                full_attribution=a.get("full_attribution", ""),
            )
            for a in APHORISMS
        ]
    )


def unseed(apps, schema_editor):
    Aphorism = apps.get_model("core", "Aphorism")
    Aphorism.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
