"""Turn on per-member term tracking for existing committee workgroups.

New committees get ``has_terms`` from the per-kind defaults; this backfills the
ones that already exist (Board, Programming Committee, …).
"""

from __future__ import annotations

from django.db import migrations


def enable(apps, schema_editor):
    Workgroup = apps.get_model("workgroups", "Workgroup")
    Workgroup.objects.filter(kind="committee").update(has_terms=True)


def disable(apps, schema_editor):
    Workgroup = apps.get_model("workgroups", "Workgroup")
    Workgroup.objects.filter(kind="committee").update(has_terms=False)


class Migration(migrations.Migration):
    dependencies = [("workgroups", "0015_workgroup_has_terms")]
    operations = [migrations.RunPython(enable, disable)]
