"""Seed the Meeting of Analysts committee (with its backing workgroup).

Idempotent. Uses historical models and the proven workgroup field set from the
Stage-4 fold-in (0006), so the auto-provision signal does not fire here — the
committee gets its workgroup but no channel until one is created. The roster is
populated later (admin / seed). Board + Programming Committee already exist.
"""

from __future__ import annotations

from django.db import migrations

SLUG = "meeting-of-analysts"
NAME = "Meeting of Analysts"
DESC = "The assembly of analysts of the School."


def seed(apps, schema_editor):
    Committee = apps.get_model("committees", "Committee")
    Workgroup = apps.get_model("workgroups", "Workgroup")
    if Committee.objects.filter(slug=SLUG).exists():
        return
    wg = Workgroup.objects.create(
        kind="committee",
        name=NAME,
        slug=SLUG,
        description=DESC,
        landing_visibility="members",
        content_visibility="members",
        has_channel=True, has_works=True, has_files=True,
        has_calendar=True, has_minutes=True, has_tasks=True, has_decisions=True,
    )
    Committee.objects.create(
        name=NAME, slug=SLUG, description=DESC, charter="", public=False, workgroup=wg,
    )


def unseed(apps, schema_editor):
    Committee = apps.get_model("committees", "Committee")
    Workgroup = apps.get_model("workgroups", "Workgroup")
    Committee.objects.filter(slug=SLUG).delete()
    Workgroup.objects.filter(slug=SLUG, kind="committee").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("committees", "0007_delete_committeemembership"),
        ("workgroups", "0002_alter_workgroup_kind"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
