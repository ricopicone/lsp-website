"""Every Analyst is automatically a member of the Meeting of Analysts.

Sets the committee workgroup's ``auto_member_role`` to the Analyst role, so
membership is derived from ``Profile.role`` (no roster rows to maintain).
Idempotent.
"""

from __future__ import annotations

from django.db import migrations

SLUG = "meeting-of-analysts"
ANALYST = "analyst"


def set_role(apps, schema_editor):
    Workgroup = apps.get_model("workgroups", "Workgroup")
    Workgroup.objects.filter(slug=SLUG, kind="committee").update(
        auto_member_role=ANALYST
    )


def clear_role(apps, schema_editor):
    Workgroup = apps.get_model("workgroups", "Workgroup")
    Workgroup.objects.filter(slug=SLUG, kind="committee").update(auto_member_role="")


class Migration(migrations.Migration):
    dependencies = [
        ("committees", "0008_seed_meeting_of_analysts"),
        ("workgroups", "0007_workgroup_auto_member_role"),
    ]
    operations = [migrations.RunPython(set_role, clear_role)]
