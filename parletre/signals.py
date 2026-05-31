"""Auto-provision a Parlêtre channel for each Workgroup.

Lives in ``parletre`` (not ``workgroups``) so the dependency points the right
way: Parlêtre knows about workgroups; workgroups stays unaware of Parlêtre.
"""

from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.text import slugify

from workgroups.models import Workgroup

from .models import Channel, ChannelCategory

#: name + sidebar position for the auto-created category, by workgroup kind.
_CATEGORY_FOR_KIND = {
    Workgroup.Kind.COMMITTEE: ("Committees", 20),
    Workgroup.Kind.CARTEL: ("Cartels", 30),
    Workgroup.Kind.WORKING_GROUP: ("Working Groups", 40),
    Workgroup.Kind.SEMINAR: ("Seminars", 50),
}


def _unique_channel_slug(workgroup) -> str:
    base = (slugify(workgroup.slug or workgroup.name) or "group")[:110]
    slug = base
    n = 2
    while Channel.objects.filter(slug=slug).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


@receiver(post_save, sender=Workgroup, dispatch_uid="parletre_provision_workgroup_channel")
def provision_workgroup_channel(sender, instance, **kwargs):
    """Give a workgroup a forum channel when it wants one and lacks it.

    Idempotent: skips when ``has_channel`` is off or a channel already exists,
    so toggling ``has_channel`` on later provisions one without duplicating.
    """
    if not instance.has_channel or instance.channels.exists():
        return

    category = None
    catinfo = _CATEGORY_FOR_KIND.get(instance.kind)
    if catinfo:
        name, position = catinfo
        category, _ = ChannelCategory.objects.get_or_create(
            name=name, defaults={"slug": slugify(name), "position": position}
        )

    Channel.objects.create(
        name=instance.name,
        slug=_unique_channel_slug(instance),
        kind=Channel.Kind.FORUM,
        access=Channel.Access.WORKGROUP,
        workgroup=instance,
        category=category,
        description=f"Discussion for {instance.name}.",
    )
