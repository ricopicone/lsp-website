"""Freud Reading Group charges an annual fee — model it as a standing group
with an annual paid *term* (not free open-join).

- open_join → False (you join by registering + paying the current term).
- Re-attach the per-year event (retired by 0009) as the group's term, so
  current members derive from its paid/comped registrations and renew yearly.
  Left unpublished/closed — staff opens registration deliberately.
- Drop the stored member rows 0009 created from registrants; current members
  now derive from the term's registrations (so they lapse/renew each year).
  Organizers (stored) are kept.

Idempotent and slug-guarded; no-ops on databases without the group.
"""

from __future__ import annotations

from django.db import migrations

WG_SLUG = "freud-reading-group"
TERM_SLUG = "freud-reading-group-2026-27"


def to_paid_term(apps, schema_editor):
    Workgroup = apps.get_model("workgroups", "Workgroup")
    WorkgroupMembership = apps.get_model("workgroups", "WorkgroupMembership")
    Event = apps.get_model("events", "Event")

    wg = Workgroup.objects.filter(slug=WG_SLUG, kind="reading_group").first()
    if wg is None:
        return

    wg.open_join = False
    wg.save(update_fields=["open_join"])

    term = Event.objects.filter(slug=TERM_SLUG).first()
    if term is not None:
        term.workgroup = wg          # re-attach as the group's term
        term.save(update_fields=["workgroup"])

    # Current members derive from the term's registrations now — drop the
    # stored member rows the free-conversion created. Keep organizers.
    WorkgroupMembership.objects.filter(workgroup=wg, role="member").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("workgroups", "0010_reading_groups_public_landing"),
        ("events", "0018_alter_pricetier_audience"),
    ]
    operations = [migrations.RunPython(to_paid_term, migrations.RunPython.noop)]
