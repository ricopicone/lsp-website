"""Registration records (architecture § 5.4)."""

from __future__ import annotations

from django.conf import settings
from django.db import models, transaction
from django.db.models import F
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
        constraints = [
            # At most one active (non-cancelled, non-refunded) Registration per
            # (user, event). Historical cancelled/refunded rows are unconstrained
            # so re-registration after cancellation works. Mirrors the partial
            # unique pattern used by ``committees.CommitteeMembership``.
            models.UniqueConstraint(
                fields=("user", "event"),
                condition=~models.Q(
                    status__in=("cancelled", "refunded")
                ),
                name="registrations_one_active_per_user_event",
            ),
        ]
        indexes = [
            models.Index(fields=("event", "status")),
            models.Index(fields=("user", "event")),
        ]

    def __str__(self):
        return f"{self.user} → {self.event} ({self.get_status_display()}, ${self.quoted_amount})"

    def cancel(self):
        """Cancel this registration. Refunds the payment if PAID.

        State machine:

        - awaiting_payment → CANCELLED (no money to move)
        - comped → CANCELLED (no payment exists)
        - paid → Stripe refund issued → REFUNDED
        - cancelled / refunded → idempotent no-op

        Pricing-code ``uses_remaining`` is restored when an active reg that
        consumed a use is cancelled, so the code is available to others (or
        for a re-register).

        Returns the Stripe ``Refund`` object when a refund was issued,
        otherwise ``None``.
        """
        from payments.models import Payment as _Payment  # avoid circular import
        from payments.refund import refund_payment  # avoid circular import

        if self.status in (self.Status.CANCELLED, self.Status.REFUNDED):
            return None

        refund = None
        with transaction.atomic():
            if self.status == self.Status.PAID:
                payment = self.payments.filter(
                    status=_Payment.Status.SUCCEEDED,
                    method=_Payment.Method.STRIPE,
                ).first()
                if payment is None:
                    raise RuntimeError(
                        f"Registration {self.id} is PAID but has no SUCCEEDED Stripe "
                        f"payment — refund must be handled manually."
                    )
                refund = refund_payment(payment)
                self.status = self.Status.REFUNDED
            else:
                self.status = self.Status.CANCELLED

            self.save(update_fields=("status",))

            if self.pricing_code_id:
                from events.models import PricingCode  # avoid circular import
                PricingCode.objects.filter(
                    pk=self.pricing_code_id,
                    max_uses__isnull=False,
                ).update(uses_remaining=F("uses_remaining") + 1)

        return refund
