"""Site-wide notifications.

A single :class:`Notification` model backs the nav bell across the whole site
— Parlêtre mentions, registration updates, cartel invitations, admissions
decisions, group activity, and so on. Rows are written through
:func:`notifications.dispatch.notify`, never created ad hoc, so the in-app and
email channels stay in sync with each member's preferences.

Notifications are *denormalized*: ``title``/``body``/``url`` are stored on the
row so the feed renders without touching the originating object (which may be
gated or later deleted). An optional generic ``target`` is kept for admin
traceability and de-duplication.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from .categories import Category, DigestCadence, EmailDelivery


class Notification(models.Model):
    """One in-app notification for one recipient."""

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    category = models.CharField(max_length=32, choices=Category.choices)

    title = models.CharField(max_length=255)
    body = models.CharField(max_length=512, blank=True)
    url = models.CharField(max_length=512, blank=True)

    # Optional generic pointer to the originating object.
    target_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.SET_NULL
    )
    target_id = models.PositiveIntegerField(null=True, blank=True)
    target = GenericForeignKey("target_type", "target_id")

    read_at = models.DateTimeField(null=True, blank=True)
    # When an accompanying email was sent (null = no email sent for this row).
    emailed_at = models.DateTimeField(null=True, blank=True)
    # Waiting to be rolled into the member's next email digest.
    digest_pending = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["recipient", "read_at"]),
            models.Index(fields=["recipient", "category"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_category_display()} → {self.recipient}"

    @property
    def is_unread(self) -> bool:
        return self.read_at is None


class NotificationPreference(models.Model):
    """A member's per-category delivery overrides.

    Stored as a JSON map ``{category: {"in_app": bool, "email": "immediate"|
    "off"}}``. Absent keys fall back to the category defaults in
    :data:`notifications.categories.CATEGORY_META`, so a fresh member needs no
    row at all. Resolution lives in :mod:`notifications.preferences`.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preference",
    )
    overrides = models.JSONField(default=dict, blank=True)
    digest_cadence = models.CharField(
        max_length=8, choices=DigestCadence.choices, default=DigestCadence.WEEKLY
    )
    last_digest_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Notification preferences for {self.user}"

    def get(self, category: str) -> dict:
        value = self.overrides.get(category)
        return value if isinstance(value, dict) else {}

    def set(self, category: str, *, in_app: bool, email: str) -> None:
        self.overrides[str(category)] = {
            "in_app": bool(in_app),
            "email": email if email in EmailDelivery.values else EmailDelivery.OFF,
        }
