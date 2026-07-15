"""Model signals for the payments app (task #439)."""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import TuitionEnrollment


@receiver(post_save, sender=TuitionEnrollment, dispatch_uid="tuition_charge_sync_save")
def _enrollment_saved(sender, instance, raw=False, **kwargs):
    if raw:
        return  # loading a fixture — don't touch charges
    from .charges import sync_tuition_charges
    sync_tuition_charges(instance.user)


@receiver(post_delete, sender=TuitionEnrollment, dispatch_uid="tuition_charge_sync_delete")
def _enrollment_deleted(sender, instance, **kwargs):
    from .charges import sync_tuition_charges
    sync_tuition_charges(instance.user)
