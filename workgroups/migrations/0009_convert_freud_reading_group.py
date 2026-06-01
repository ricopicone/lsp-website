"""Convert the Freud Reading Group from a per-year Event-backed offering to a
standing, continuously-joinable reading group.

- Rename to "Freud Reading Group" (drop the year from name + slug).
- Make it continuous (no end date) + open_join.
- Faculty memberships → Organizer; paid/comped registrants of the linked
  event(s) → stored members.
- Retire the per-year Event(s): unlink from the workgroup, unpublish, close.

Idempotent and guarded by slug, so it no-ops on databases without the group
(local / CI). Reverse = noop.
"""

from __future__ import annotations

from django.db import migrations

OLD_SLUG = "freud-reading-group-2026-27"
NEW_SLUG = "freud-reading-group"


def convert(apps, schema_editor):
    Workgroup = apps.get_model("workgroups", "Workgroup")
    WorkgroupMembership = apps.get_model("workgroups", "WorkgroupMembership")
    Registration = apps.get_model("registrations", "Registration")
    from django.utils import timezone

    wg = Workgroup.objects.filter(slug=OLD_SLUG, kind="reading_group").first()
    if wg is None:
        return

    today = timezone.now().date()
    wg.name = "Freud Reading Group"
    if not Workgroup.objects.filter(slug=NEW_SLUG).exists():
        wg.slug = NEW_SLUG
    wg.open_join = True
    wg.end_date = None   # continuous / ongoing

    # Retire linked events; carry their paid/comped registrants into the roster.
    for event in list(wg.events.all()):
        if wg.start_date is None and event.start_date:
            wg.start_date = event.start_date
        regs = Registration.objects.filter(
            event=event, status__in=("paid", "comped")
        )
        for reg in regs:
            if reg.user_id and not WorkgroupMembership.objects.filter(
                workgroup=wg, user_id=reg.user_id, end_date__isnull=True
            ).exists():
                WorkgroupMembership.objects.create(
                    workgroup=wg, user_id=reg.user_id, role="member", start_date=today
                )
        event.workgroup = None
        event.published = False
        event.status = "closed"
        event.save()

    # Faculty (who ran it) become Organizers of the standing group.
    WorkgroupMembership.objects.filter(
        workgroup=wg, role="faculty", end_date__isnull=True
    ).update(role="organizer")

    wg.save()


class Migration(migrations.Migration):
    dependencies = [
        ("workgroups", "0008_workgroup_open_join_alter_workgroupmembership_role"),
        ("events", "0017_event_requires_faculty_approval"),
        ("registrations", "0004_remove_registration_registrations_one_active_per_user_event_and_more"),
    ]
    operations = [migrations.RunPython(convert, migrations.RunPython.noop)]
