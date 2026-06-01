"""Reading group pages are publicly visible (like seminars); roster + content
stay members-only. Set landing_visibility=public on existing reading groups.
Idempotent; no-ops where there are none.
"""

from __future__ import annotations

from django.db import migrations


def public_landing(apps, schema_editor):
    Workgroup = apps.get_model("workgroups", "Workgroup")
    Workgroup.objects.filter(kind="reading_group").update(landing_visibility="public")


class Migration(migrations.Migration):
    dependencies = [
        ("workgroups", "0009_convert_freud_reading_group"),
    ]
    operations = [migrations.RunPython(public_landing, migrations.RunPython.noop)]
