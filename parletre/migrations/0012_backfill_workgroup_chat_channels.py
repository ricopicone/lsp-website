"""W1b: backfill a Chat channel for each workgroup that has a Discuss (forum)
channel but no chat channel yet (existing workgroups were provisioned with only
a forum channel). Additive; reverse = noop. Data migrations use historical
models so the provisioning signal does not fire — we create channels here.
"""

from django.db import migrations
from django.utils.text import slugify

_CATEGORY_FOR_KIND = {
    "committee": ("Committees", 20),
    "cartel": ("Cartels", 30),
    "reading_group": ("Reading Groups", 35),
    "working_group": ("Working Groups", 40),
    "seminar": ("Seminars", 50),
}


def backfill(apps, schema_editor):
    Workgroup = apps.get_model("workgroups", "Workgroup")
    Channel = apps.get_model("parletre", "Channel")
    ChannelCategory = apps.get_model("parletre", "ChannelCategory")

    def unique_slug(base):
        base = (slugify(base) or "group")[:100] + "-chat"
        slug, n = base, 2
        while Channel.objects.filter(slug=slug).exists():
            slug = f"{base}-{n}"
            n += 1
        return slug

    cats = {}
    created = 0
    for wg in Workgroup.objects.filter(has_channel=True):
        kinds = set(wg.channels.values_list("kind", flat=True))
        if "forum" not in kinds or "chat" in kinds:
            continue  # only workgroups that have a forum but no chat
        cat = None
        catinfo = _CATEGORY_FOR_KIND.get(wg.kind)
        if catinfo:
            if wg.kind not in cats:
                name, pos = catinfo
                cats[wg.kind], _ = ChannelCategory.objects.get_or_create(
                    name=name, defaults={"slug": slugify(name), "position": pos}
                )
            cat = cats[wg.kind]
        Channel.objects.create(
            name=f"{wg.name} chat"[:120],
            slug=unique_slug(wg.slug or wg.name),
            kind="chat",
            access="workgroup",
            workgroup=wg,
            category=cat,
            description=f"Chat for {wg.name}.",
        )
        created += 1
    print(f"  backfilled {created} workgroup chat channel(s).")


class Migration(migrations.Migration):

    dependencies = [
        ("parletre", "0011_alter_channel_access"),
        ("workgroups", "0002_alter_workgroup_kind"),
    ]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
