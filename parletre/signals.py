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
    Workgroup.Kind.READING_GROUP: ("Reading Groups", 35),
    Workgroup.Kind.WORKING_GROUP: ("Working Groups", 40),
    Workgroup.Kind.SEMINAR: ("Seminars", 50),
}


def _unique_channel_slug(workgroup, suffix="") -> str:
    base = (slugify(workgroup.slug or workgroup.name) or "group")[: 105 - len(suffix)] + suffix
    slug = base
    n = 2
    while Channel.objects.filter(slug=slug).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


def _category_for(kind):
    catinfo = _CATEGORY_FOR_KIND.get(kind)
    if not catinfo:
        return None
    name, position = catinfo
    cat, _ = ChannelCategory.objects.get_or_create(
        name=name, defaults={"slug": slugify(name), "position": position}
    )
    return cat


def provision_channels(workgroup):
    """Ensure the workgroup has its Discuss (forum) + Chat + Video channels.
    Idempotent per kind — creates only the ones missing. The Video channel's room
    resolves to the workgroup's own room (shared with the Meet tab)."""
    if not workgroup.has_channel:
        return
    existing = set(workgroup.channels.values_list("kind", flat=True))
    category = _category_for(workgroup.kind)
    if Channel.Kind.FORUM not in existing:
        Channel.objects.create(
            name=workgroup.name, slug=_unique_channel_slug(workgroup),
            kind=Channel.Kind.FORUM, access=Channel.Access.WORKGROUP,
            workgroup=workgroup, category=category,
            description=f"Discussion for {workgroup.name}.",
        )
    if Channel.Kind.CHAT not in existing:
        Channel.objects.create(
            name=f"{workgroup.name} chat"[:120], slug=_unique_channel_slug(workgroup, "-chat"),
            kind=Channel.Kind.CHAT, access=Channel.Access.WORKGROUP,
            workgroup=workgroup, category=category,
            description=f"Chat for {workgroup.name}.",
        )
    if Channel.Kind.VIDEO not in existing:
        Channel.objects.create(
            name=f"{workgroup.name} video"[:120], slug=_unique_channel_slug(workgroup, "-video"),
            kind=Channel.Kind.VIDEO, access=Channel.Access.WORKGROUP,
            workgroup=workgroup, category=category,
            description=f"Video room for {workgroup.name}.",
        )


@receiver(post_save, sender=Workgroup, dispatch_uid="parletre_provision_workgroup_channel")
def provision_workgroup_channel(sender, instance, **kwargs):
    """Auto-provision the workgroup's Discuss + Chat channels on save."""
    provision_channels(instance)
