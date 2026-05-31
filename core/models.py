"""Core models. Currently: the footer aphorism (staff-editable)."""

from __future__ import annotations

from django.core.cache import cache
from django.db import models
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

#: Cache key for the active-aphorism list (see ``core.context_processors``).
APHORISM_CACHE_KEY = "core:aphorisms:active"


class Aphorism(models.Model):
    """A Lacanian aphorism surfaced in the site footer (one per page render).

    Editable by staff via the admin / Web Coordinator panel. The table is
    seeded once from ``core.aphorisms.APHORISMS`` by a data migration; after
    that this model is the source of truth.
    """

    quote = models.TextField(help_text="The visible aphorism.")
    short_attribution = models.CharField(
        max_length=120,
        blank=True,
        help_text="Small chip shown next to the quote (e.g. “Seminar XI”).",
    )
    full_attribution = models.TextField(
        blank=True,
        help_text="Bibliographic detail; shown as the hover tooltip.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Only active aphorisms appear in the footer rotation.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("short_attribution", "pk")

    def __str__(self) -> str:
        return self.quote if len(self.quote) <= 60 else self.quote[:57] + "…"


@receiver(post_save, sender=Aphorism)
@receiver(post_delete, sender=Aphorism)
def _clear_aphorism_cache(**kwargs):
    """Drop the cached active list whenever an aphorism changes."""
    cache.delete(APHORISM_CACHE_KEY)
