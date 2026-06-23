"""Keep ``Session.sequence`` in chronological sync.

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


@receiver(post_delete, sender=Session)
def _resequence_on_delete(sender, instance, **kwargs):
    # Skip when the parent Event is itself being deleted (cascade) — its
    # sessions are all going away and the event row may already be gone.
    if Event.objects.filter(pk=instance.event_id).exists():
        Event.objects.get(pk=instance.event_id).resequence_sessions()
