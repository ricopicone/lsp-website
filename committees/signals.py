"""Keep the school officers synced whenever the Board roster changes."""

from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from workgroups.models import WorkgroupMembership, roster_changed

from .officers import sync_school_officers

_OFFICER_ROLES = {WorkgroupMembership.Role.CHAIR, WorkgroupMembership.Role.CO_CHAIR}


def _is_board(workgroup) -> bool:
    try:
        return workgroup.committee.slug == "board"
    except ObjectDoesNotExist:
        return False


@receiver(post_save, sender=WorkgroupMembership)
@receiver(post_delete, sender=WorkgroupMembership)
def _sync_school_officers_on_membership_write(sender, instance, **kwargs):
    """Covers creates, ``.save()`` edits (set_role), the Django admin, and seed —
    all of which fire the model signals."""
    # Cheap gate first: only Chair/Co-chair rows can change officers.
    if instance.role not in _OFFICER_ROLES:
        return
    if _is_board(instance.workgroup):
        sync_school_officers()


@receiver(roster_changed)
def _sync_school_officers_on_roster_changed(sender, workgroup, **kwargs):
    """Covers the bulk ``.update()`` paths (remove_member / leave) that bypass
    the model signals. Idempotent, so re-syncing on any Board roster change is
    fine even when the removed member wasn't an officer."""
    if _is_board(workgroup):
        sync_school_officers()
