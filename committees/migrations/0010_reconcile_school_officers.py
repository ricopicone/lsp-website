"""One-time reconcile: point the President / Vice-President StaffRoles at the
Board's current Chair / Co-chair (task #428 follow-on). Idempotent."""

from __future__ import annotations

from django.db import migrations
from django.db.models import Q


def reconcile(apps, schema_editor):
    from django.utils import timezone

    Committee = apps.get_model("committees", "Committee")
    StaffRole = apps.get_model("core", "StaffRole")

    board = (
        Committee.objects.filter(slug="board").select_related("workgroup").first()
    )
    if board is None or board.workgroup_id is None:
        return
    today = timezone.localdate()
    serving = board.workgroup.memberships.filter(
        Q(end_date__isnull=True) | Q(end_date__gt=today)
    )
    mapping = {"chair": "president", "co_chair": "vice_president"}
    for role_value, key in mapping.items():
        holders = [m.user for m in serving if m.role == role_value]
        role = StaffRole.objects.filter(key=key).first()
        if role is not None:
            role.holders.set(holders)


class Migration(migrations.Migration):
    dependencies = [
        ("committees", "0009_meeting_of_analysts_auto_member"),
        ("core", "0012_seed_president_vice_president"),
        ("workgroups", "0025_meetingseries_timezone"),
    ]
    operations = [migrations.RunPython(reconcile, migrations.RunPython.noop)]
