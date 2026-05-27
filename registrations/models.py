"""Registration records (architecture § 5.4)."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Registration(models.Model):
    class Status(models.TextChoices):
        AWAITING_PAYMENT = "awaiting_payment", _("Awaiting payment")
        PAID = "paid", _("Paid")
        COMPED = "comped", _("Comped")
        CANCELLED = "cancelled", _("Cancelled")
        REFUNDED = "refunded", _("Refunded")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="registrations",
    )
    event = models.ForeignKey(
        "events.Event",
        on_delete=models.PROTECT,
        related_name="registrations",
    )
    sessions = models.ManyToManyField(
        "events.Session",
        blank=True,
        related_name="registrations",
        help_text="Set for per-class registration (REG-6); empty for whole-event.",
    )
    price_tier = models.ForeignKey(
        "events.PriceTier",
        on_delete=models.PROTECT,
        related_name="registrations",
    )
    pricing_code = models.ForeignKey(
        "events.PricingCode",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="redemptions",
        help_text="The code redeemed at registration time, if any.",
    )
    quoted_amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        help_text="Amount due — resolved at registration time.",
    )
    quoted_explanation = models.CharField(
        max_length=500,
        blank=True,
        help_text="Human-readable explanation of how quoted_amount was computed.",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.AWAITING_PAYMENT,
    )
    staff_notes = models.TextField(
        blank=True,
        help_text="Manual override notes (REG-14).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("event", "status")),
            models.Index(fields=("user", "event")),
        ]

    def __str__(self):
        return f"{self.user} → {self.event} ({self.get_status_display()}, ${self.quoted_amount})"
