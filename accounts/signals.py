"""Signal handlers for the accounts app."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile, User


@receiver(post_save, sender=User)
def ensure_profile(sender, instance, created, **kwargs):
    """Give every newly created user a Profile."""
    if created:
        Profile.objects.get_or_create(user=instance)
