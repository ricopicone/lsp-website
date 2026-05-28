"""Resolve any existing duplicate active (user, event) Registrations.

Runs before the partial unique constraint is added in 0003. For each
(user, event) with more than one non-cancelled/non-refunded Registration,
keep the most useful row (a PAID row wins; otherwise the most recently
created) and mark the others ``cancelled`` with a staff_notes line so
the cleanup is auditable.
"""

from django.db import migrations


ACTIVE_STATUSES = ("awaiting_payment", "paid")


def cleanup_duplicates(apps, schema_editor):
    Registration = apps.get_model("registrations", "Registration")
    seen = {}
    for reg in Registration.objects.filter(status__in=ACTIVE_STATUSES).order_by("id"):
        seen.setdefault((reg.user_id, reg.event_id), []).append(reg)

    for (user_id, event_id), regs in seen.items():
        if len(regs) <= 1:
            continue
        # Prefer PAID over AWAITING_PAYMENT; within a status, prefer the most
        # recently created row.
        regs.sort(
            key=lambda r: (0 if r.status == "paid" else 1, -r.created_at.timestamp())
        )
        keep = regs[0]
        for r in regs[1:]:
            note = (
                f"\n[auto-cleanup migration 0002] Cancelled in favor of "
                f"registration #{keep.id} when enforcing one active "
                f"registration per (user, event)."
            )
            r.status = "cancelled"
            r.staff_notes = (r.staff_notes or "") + note
            r.save(update_fields=("status", "staff_notes"))


class Migration(migrations.Migration):
    dependencies = [("registrations", "0001_initial")]
    operations = [migrations.RunPython(cleanup_duplicates, migrations.RunPython.noop)]
