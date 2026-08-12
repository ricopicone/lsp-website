"""Auto-provision a Parlêtre channel for each Workgroup.

Lives in ``parletre`` (not ``workgroups``) so the dependency points the right
way: Parlêtre knows about workgroups; workgroups stays unaware of Parlêtre.
"""

from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.text import slugify

from workgroups.models import Workgroup, renamed

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


#: How each channel's name and description are derived from the workgroup's
#: name. One definition, read by both provisioning and renaming — two copies
#: would drift, and the rename can only recognise an untouched channel by
#: re-deriving what the *old* name produced.
_DERIVED = {
    Channel.Kind.FORUM: ("{name}", "Discussion for {name}."),
    Channel.Kind.CHAT: ("{name} chat", "Chat for {name}."),
    Channel.Kind.VIDEO: ("{name} video", "Video room for {name}."),
}


def derived_channel_text(kind, workgroup_name: str) -> tuple[str, str]:
    """The ``(name, description)`` a channel of ``kind`` gets from a workgroup
    called ``workgroup_name``. Name is capped at the field's 120 characters."""
    name_tpl, desc_tpl = _DERIVED[kind]
    return name_tpl.format(name=workgroup_name)[:120], desc_tpl.format(name=workgroup_name)


def provision_channels(workgroup):
    """Ensure the workgroup has its Discuss (forum) + Chat + Video channels.
    Idempotent per kind — creates only the ones missing. The Video channel's room
    resolves to the workgroup's own room (shared with the Meet tab)."""
    if not workgroup.has_channel:
        return
    existing = set(workgroup.channels.values_list("kind", flat=True))
    category = _category_for(workgroup.kind)
    slug_suffix = {
        Channel.Kind.FORUM: "", Channel.Kind.CHAT: "-chat", Channel.Kind.VIDEO: "-video",
    }
    for kind in (Channel.Kind.FORUM, Channel.Kind.CHAT, Channel.Kind.VIDEO):
        if kind in existing:
            continue
        name, description = derived_channel_text(kind, workgroup.name)
        Channel.objects.create(
            name=name, slug=_unique_channel_slug(workgroup, slug_suffix[kind]),
            kind=kind, access=Channel.Access.WORKGROUP,
            workgroup=workgroup, category=category, description=description,
        )


@receiver(renamed, dispatch_uid="parletre_rename_workgroup_channels")
def rename_workgroup_channels(sender, workgroup, old_name, new_name, **kwargs):
    """Follow a workgroup rename onto its auto-provisioned channels (task #568).

    Only the name and description move — a channel's slug is its URL. Each field
    is rewritten only if it still holds what the *old* workgroup name derived:
    ``Channel.name`` is editable in Django admin, and a room somebody
    deliberately renamed must not be silently reverted.
    """
    for channel in workgroup.channels.all():
        if channel.kind not in _DERIVED:
            continue
        was_name, was_desc = derived_channel_text(channel.kind, old_name)
        now_name, now_desc = derived_channel_text(channel.kind, new_name)
        fields = []
        if channel.name == was_name and channel.name != now_name:
            channel.name = now_name
            fields.append("name")
        if channel.description == was_desc and channel.description != now_desc:
            channel.description = now_desc
            fields.append("description")
        if fields:
            channel.save(update_fields=fields)


@receiver(post_save, sender=Workgroup, dispatch_uid="parletre_provision_workgroup_channel")
def provision_workgroup_channel(sender, instance, **kwargs):
    """Auto-provision the workgroup's Discuss + Chat channels on save."""
    provision_channels(instance)
