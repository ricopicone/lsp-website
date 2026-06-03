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


class StaffRole(models.Model):
    """An operational coordinator role and who holds it.

    A coordinator (Web, Treasurer, Cartel, …) is an *independent capability*,
    not a committee or workgroup — those model collaborating groups (rosters,
    Parlêtre channels). This mirrors the ``Profile.is_lsp_staff`` precedent but
    enumerates several such roles in one place and tracks their holders, so a
    handoff is just reassigning ``holders`` in the admin.

    ``key`` is the stable identifier code gates on (a control panel is wired to
    a known key). The well-known keys are constants below; rows are seeded by a
    data migration. Superusers implicitly hold every role (see ``core.access``).
    """

    # Well-known keys that code gates on.
    WEB_COORDINATOR = "web_coordinator"
    TREASURER = "treasurer"
    CARTEL_COORDINATOR = "cartel_coordinator"
    LSP_STAFF = "lsp_staff"
    ADMIN_ASSISTANT = "admin_assistant"
    WEB_DEVELOPER = "web_developer"

    key = models.SlugField(
        max_length=50,
        unique=True,
        help_text="Stable identifier code uses to gate a control panel. "
        "Don't rename an existing key — it would orphan its panel.",
    )
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    holders = models.ManyToManyField(
        "accounts.User",
        blank=True,
        related_name="staff_roles",
        help_text="Users who hold this role (superusers hold every role).",
    )

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class ImpersonationLog(models.Model):
    """Audit trail: a superuser viewed the site as another user (impersonation).

    Recorded when impersonation *starts*; ``ended_at`` is stamped on exit.
    """

    impersonator = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE,
        related_name="impersonations_made",
    )
    target = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE,
        related_name="impersonations_of",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    read_only = models.BooleanField(
        default=True, help_text="Whether writes were blocked (real member, not a persona)."
    )

    class Meta:
        ordering = ("-started_at",)

    def __str__(self) -> str:
        return f"{self.impersonator} → {self.target} @ {self.started_at:%Y-%m-%d %H:%M}"
