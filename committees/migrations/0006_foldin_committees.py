"""Stage-4 committee fold-in (big-bang).

Board + Programming Committee become Workgroup(kind=committee) with their
roster relocated to WorkgroupMembership; existing committee-access Parlêtre
channels are repointed to access=workgroup. LSP Staff leaves the committee
model entirely: its members get the ``Profile.is_lsp_staff`` designation and a
single LSP Staff channel (access=lsp_staff), and the committee row is deleted.

Data migrations run against historical models, so the auto-provision signal
(registered for the real Workgroup class) does NOT fire here — channels are
created / repointed explicitly, avoiding duplicates.
"""

from django.db import migrations

LSP_STAFF_SLUG = "lsp-staff"


def _unique(model, field, base, cap):
    base = (base or "x")[:cap]
    value, n = base, 2
    while model.objects.filter(**{field: value}).exists():
        value = f"{base}-{n}"
        n += 1
    return value


def foldin(apps, schema_editor):
    Committee = apps.get_model("committees", "Committee")
    CommitteeMembership = apps.get_model("committees", "CommitteeMembership")
    Workgroup = apps.get_model("workgroups", "Workgroup")
    WorkgroupMembership = apps.get_model("workgroups", "WorkgroupMembership")
    Channel = apps.get_model("parletre", "Channel")
    ChannelCategory = apps.get_model("parletre", "ChannelCategory")
    Profile = apps.get_model("accounts", "Profile")

    committees_cat = None

    for committee in Committee.objects.all():
        memberships = list(CommitteeMembership.objects.filter(committee=committee))
        channels = list(Channel.objects.filter(committee=committee))

        if committee.slug == LSP_STAFF_SLUG:
            # Designation, not a group. Grant is_lsp_staff to active members.
            active_user_ids = [m.user_id for m in memberships if m.end_date is None]
            Profile.objects.filter(user_id__in=active_user_ids).update(is_lsp_staff=True)
            # One LSP Staff channel (access=lsp_staff): repoint an existing one,
            # else create.
            if channels:
                ch = channels[0]
                ch.access = "lsp_staff"
                ch.committee = None
                ch.save()
                for extra in channels[1:]:
                    extra.access = "lsp_staff"
                    extra.committee = None
                    extra.save()
            else:
                Channel.objects.create(
                    name="LSP Staff",
                    slug=_unique(Channel, "slug", "lsp-staff", 110),
                    kind="forum",
                    access="lsp_staff",
                    description="LSP Staff.",
                )
            CommitteeMembership.objects.filter(committee=committee).delete()
            committee.delete()
            continue

        # Board / PC / any other committee -> Workgroup(kind=committee).
        wg = Workgroup.objects.create(
            kind="committee",
            name=committee.name,
            slug=_unique(Workgroup, "slug", committee.slug, 140),
            description=committee.description or "",
            landing_visibility="public" if committee.public else "members",
            content_visibility="members",
            has_channel=True, has_works=True, has_files=True,
            has_calendar=True, has_minutes=True, has_tasks=True, has_decisions=True,
        )
        committee.workgroup = wg
        committee.save()

        for m in memberships:
            WorkgroupMembership.objects.create(
                workgroup=wg,
                user_id=m.user_id,
                role=m.role_in_committee,
                start_date=m.start_date,
                end_date=m.end_date,
            )

        if channels:
            for ch in channels:
                ch.access = "workgroup"
                ch.workgroup = wg
                ch.committee = None
                ch.save()
        else:
            if committees_cat is None:
                committees_cat, _ = ChannelCategory.objects.get_or_create(
                    name="Committees", defaults={"slug": "committees", "position": 20}
                )
            Channel.objects.create(
                name=committee.name,
                slug=_unique(Channel, "slug", committee.slug, 110),
                kind="forum",
                access="workgroup",
                workgroup=wg,
                category=committees_cat,
                description=f"Discussion for {committee.name}.",
            )


class Migration(migrations.Migration):

    dependencies = [
        ("committees", "0005_committee_workgroup"),
        ("workgroups", "0001_initial"),
        ("accounts", "0018_profile_is_lsp_staff"),
        ("parletre", "0011_alter_channel_access"),
    ]

    operations = [
        migrations.RunPython(foldin, migrations.RunPython.noop),
    ]
