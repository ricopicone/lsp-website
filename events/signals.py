"""Keep derived copies of event data in sync.

``Session.sequence`` follows the session dates, and an offering workgroup's
display name follows its featured event's title (task #568).

The session number shown on the event page is read as "the Nth meeting," but
``sequence`` is a stored field assigned at insertion time, so adding/removing a
session out of date order (or moving a date in admin) used to leave the label
stale — e.g. a newly-added October meeting numbered ``#9`` while sitting second
by date. These signals re-derive ``sequence`` from ``start_at`` whenever a
session changes. ``Event.resequence_sessions`` writes via ``bulk_update``, which
fires no save signals, so there's no recursion.
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Event, Session


@receiver(post_save, sender=Session)
def _resequence_on_save(sender, instance, **kwargs):
    instance.event.resequence_sessions()


@receiver(post_save, sender=Event, dispatch_uid="events_sync_workgroup_name")
def _sync_workgroup_name(sender, instance, update_fields=None, **kwargs):
    """An offering's workgroup name follows its title (task #568).

    A signal rather than a call in the edit views because the title has several
    write paths — the faculty edit form, ``EventChangeRequest.apply``, the PC's
    program admin, Django admin, the program import scripts — and the stale name
    is what faculty actually see (a seminar's event page redirects to its
    Workspace). Renaming sends nothing and charges nobody, so unlike the
    billing side-effects of tasks #485/#564 there is no reason to hold it back
    from the staff paths.

    ``sync_name_from_primary_event`` is the guard for *which* workgroup: it
    returns False for the Program Committee's, which PC-organized events share.
    """
    if instance.workgroup_id is None:
        return
    if update_fields is not None and "title" not in update_fields:
        return
    instance.workgroup.sync_name_from_primary_event()


@receiver(post_delete, sender=Session)
def _resequence_on_delete(sender, instance, **kwargs):
    # Skip when the parent Event is itself being deleted (cascade) — its
    # sessions are all going away and the event row may already be gone.
    if Event.objects.filter(pk=instance.event_id).exists():
        Event.objects.get(pk=instance.event_id).resequence_sessions()
