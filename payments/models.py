"""Payments, receipts, and the dues lifecycle (architecture § 5.5, REG-12)."""

from __future__ import annotations

from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class DuesPeriod(models.Model):
    """An academic year's dues cycle (REG-12).

    Determines the amount owed, when it's due, and (via the future
    ``block_registration_when_unpaid`` flag) whether unpaid obligated
    members can register for events. Use :meth:`current` to find the
    period covering today.
    """

    name = models.CharField(max_length=100, unique=True, help_text="e.g. AY 2026–2027")
    slug = models.SlugField(max_length=100, unique=True)
    start_date = models.DateField(help_text="First day of the academic year.")
    due_date = models.DateField(help_text="Payment due by this date.")
    end_date = models.DateField(help_text="Last day of the academic year.")
    dues_amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        help_text="Amount owed by each obligated member.",
    )
    block_registration_when_unpaid = models.BooleanField(
        default=False,
        help_text=(
            "Future flag — not currently enforced. When True, the registration "
            "view will refuse event registrations from obligated unpaid users."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-start_date",)

    def __str__(self):
        return self.name

    @classmethod
    def current(cls, on_date=None):
        """Return the DuesPeriod containing ``on_date`` (default today), or None."""
        on = on_date or timezone.now().date()
        return cls.objects.filter(start_date__lte=on, end_date__gte=on).first()


class DuesReminder(models.Model):
    """One row per reminder email sent to a user for a given DuesPeriod.

    Drives the weekly throttle: the send command skips users with a
    reminder logged in the last seven days.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="dues_reminders",
    )
    dues_period = models.ForeignKey(
        DuesPeriod,
        on_delete=models.CASCADE,
        related_name="reminders",
    )
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-sent_at",)
        indexes = [models.Index(fields=("user", "dues_period", "-sent_at"))]

    def __str__(self):
        return f"{self.user} ← {self.dues_period} @ {self.sent_at.isoformat()}"


class Payment(models.Model):
    """A single money movement — covers registrations, dues, and donations.

    ``payment_type`` distinguishes them so they report separately in
    bookkeeping (REG-2, REG-13). For registration payments, ``registration``
    points to the Registration row; for dues and donations it's null.
    """

    class Type(models.TextChoices):
        REGISTRATION = "registration", _("Registration")
        DUES = "dues", _("Dues")
        DONATION = "donation", _("Donation")

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        SUCCEEDED = "succeeded", _("Succeeded")
        FAILED = "failed", _("Failed")
        REFUNDED = "refunded", _("Refunded")

    class Method(models.TextChoices):
        STRIPE = "stripe", _("Stripe")
        OFFLINE = "offline", _("Offline / manual")

    payment_type = models.CharField(max_length=20, choices=Type.choices)
    registration = models.ForeignKey(
        "registrations.Registration",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payments",
        help_text="Null for dues and donations.",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
    )
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    currency = models.CharField(max_length=3, default="usd")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.STRIPE)
    stripe_payment_intent_id = models.CharField(max_length=120, blank=True, db_index=True)
    stripe_checkout_session_id = models.CharField(
        max_length=120,
        blank=True,
        db_index=True,
        help_text="Set on Stripe payments; used to look up Payment from a webhook event.",
    )
    email = models.EmailField(
        blank=True,
        help_text=(
            "Receipt-delivery email for anonymous payments (typically donations "
            "without an account). Falls back to user.email when a user is attached."
        ),
    )
    dues_period = models.ForeignKey(
        DuesPeriod,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payments",
        help_text="The dues cycle this payment satisfies — set for type=DUES.",
    )
    notes = models.TextField(blank=True, help_text="Staff notes — e.g. for offline payments.")
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            # When set (non-empty), Stripe checkout session id must be unique. This
            # is the natural idempotency key for incoming webhooks.
            models.UniqueConstraint(
                fields=("stripe_checkout_session_id",),
                condition=~models.Q(stripe_checkout_session_id=""),
                name="payments_unique_stripe_session_id",
            ),
        ]
        indexes = [
            models.Index(fields=("status",)),
            models.Index(fields=("payment_type", "status")),
        ]

    def __str__(self):
        target = (
            f"reg #{self.registration_id}"
            if self.registration_id
            else self.get_payment_type_display().lower()
        )
        return f"${self.amount} {self.currency.upper()} ({self.get_status_display()}, {target})"

    def mark_succeeded(self, *, save=True) -> None:
        """Idempotent: mark payment as succeeded and timestamp paid_at."""
        if self.status == self.Status.SUCCEEDED:
            return
        self.status = self.Status.SUCCEEDED
        if self.paid_at is None:
            self.paid_at = timezone.now()
        if save:
            self.save(update_fields=("status", "paid_at"))

    @property
    def recipient_email(self) -> str | None:
        """Where to deliver the receipt: the user's email, or the payment's own."""
        if self.user_id and self.user.email:
            return self.user.email
        return self.email or None


class Receipt(models.Model):
    """Auto-generated receipt for a successful Payment (REG-7).

    ``receipt_number`` is sequential within a year, formatted ``LSP-YYYY-NNNN``.
    Use :meth:`create_for_payment` to get one atomically.
    """

    payment = models.OneToOneField(
        Payment, on_delete=models.CASCADE, related_name="receipt"
    )
    receipt_number = models.CharField(max_length=20, unique=True)
    issued_at = models.DateTimeField(auto_now_add=True)
    emailed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-issued_at",)

    def __str__(self):
        return self.receipt_number

    @classmethod
    def create_for_payment(cls, payment: Payment, *, max_retries: int = 5) -> Receipt:
        """Create a Receipt with the next sequential LSP-YYYY-NNNN number.

        Retries on IntegrityError if another concurrent caller grabbed the
        same number. Five retries is well beyond what LSP volume will see.
        """
        year = timezone.now().year
        prefix = f"LSP-{year}-"
        for _attempt in range(max_retries):
            with transaction.atomic():
                last = (
                    cls.objects.filter(receipt_number__startswith=prefix)
                    .order_by("-receipt_number")
                    .first()
                )
                next_num = (
                    int(last.receipt_number.rsplit("-", 1)[-1]) + 1 if last else 1
                )
                try:
                    return cls.objects.create(
                        payment=payment,
                        receipt_number=f"{prefix}{next_num:04d}",
                    )
                except IntegrityError:
                    continue
        raise RuntimeError(
            f"Could not generate a unique receipt number after {max_retries} retries."
        )
