"""Registration records (architecture § 5.4)."""

from __future__ import annotations

from django.conf import settings
from django.db import models, transaction
from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Registration(models.Model):
    class Status(models.TextChoices):
        PENDING_APPROVAL = "pending_approval", _("Pending faculty approval")
        AWAITING_PAYMENT = "awaiting_payment", _("Awaiting payment")
        PAID = "paid", _("Paid")
        COMPED = "comped", _("Comped")
        DECLINED = "declined", _("Declined by faculty")
        CANCELLED = "cancelled", _("Cancelled")
        REFUNDED = "refunded", _("Refunded")

    #: Statuses that keep a row off a roster — the person isn't coming. Shared
    #: by the roster CSV (REG-10) and both on-screen rosters, which had drifted:
    #: the CSV excluded these while the screens showed faculty their own
    #: cancelled test registrations. DECLINED stays visible on purpose, so
    #: faculty can see who they turned away.
    INACTIVE_ROSTER_STATUSES = ("cancelled", "refunded")

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
    # Faculty-approval flow (for events with requires_faculty_approval).
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="registration_decisions",
        help_text="Faculty member who approved / declined this registration.",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decline_reason = models.TextField(blank=True)
    #: When we last emailed a reminder for this reg's current state (faculty
    #: approval reminder while PENDING_APPROVAL; payment reminder while an
    #: approved AWAITING_PAYMENT). Reset on each state transition.
    reminded_at = models.DateTimeField(null=True, blank=True)
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
                    status__in=("cancelled", "refunded", "declined")
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

    def cancel(self, *, refund: bool = True):
        """Cancel this registration. Refunds the payment if PAID.

        State machine:

        - awaiting_payment → CANCELLED (no money to move)
        - comped → CANCELLED (no payment exists)
        - paid → Stripe refund issued → REFUNDED
        - cancelled / refunded → idempotent no-op

        ``refund=False`` releases the place without moving money. Removing
        and refunding are two decisions and a staff removal states both
        (task #627); it is also what makes a payment-plan or offline-paid
        registration cancellable at all, since everything that refuses to
        refund one — ``PlanRefundRequiresTreasurer``, and the RuntimeError
        raised when no Stripe payment can be found — lives inside the refund
        branch this skips.

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

        issued = None
        with transaction.atomic():
            if refund and self.status == self.Status.PAID:
                from payments.refund import PlanRefundRequiresTreasurer
                from payments.registration_plans import is_on_plan

                succeeded = self.payments.filter(
                    status=_Payment.Status.SUCCEEDED,
                    method=_Payment.Method.STRIPE,
                )
                # A plan pays one registration several times. Refunding the
                # first row we find would under-refund and call the whole
                # thing refunded — a latent bug for any multi-payment
                # registration, not only a plan (task #501).
                if is_on_plan(self) or succeeded.count() > 1:
                    raise PlanRefundRequiresTreasurer(
                        "This registration was paid in installments; the "
                        "treasurer settles the refund by hand."
                    )
                payment = succeeded.first()
                if payment is None:
                    raise RuntimeError(
                        f"Registration {self.id} is PAID but has no SUCCEEDED Stripe "
                        f"payment — refund must be handled manually."
                    )
                issued = refund_payment(payment)
                self.status = self.Status.REFUNDED
            else:
                self.status = self.Status.CANCELLED

            self.save(update_fields=("status",))

            # Kill any Checkout session still open on this registration, or a
            # stale tab can charge for a place that no longer exists (and, for
            # someone who cancelled in order to re-register with a code, for
            # one they now hold for free).
            from payments.stripe_sync import expire_open_sessions
            expire_open_sessions(
                self, reason="Registration cancelled; checkout expired.",
            )

            if self.pricing_code_id:
                from events.models import PricingCode  # avoid circular import
                PricingCode.objects.filter(
                    pk=self.pricing_code_id,
                    max_uses__isnull=False,
                ).update(uses_remaining=F("uses_remaining") + 1)

        return issued

    @property
    def on_payment_plan(self) -> bool:
        """Whether this registration is being paid in installments (task
        #501). A property so the two roster surfaces share one answer rather
        than each annotating their own queryset."""
        from payments.registration_plans import is_on_plan
        return is_on_plan(self)

    @property
    def is_removable(self) -> bool:
        """Whether the console's Remove button applies (task #627). False for
        the three statuses that already closed the row."""
        from .services import TERMINAL_STATUSES
        return self.status not in TERMINAL_STATUSES

    @property
    def refundable_amount(self):
        """What the site could refund on its own, or ``None``.

        Set only where exactly one succeeded Stripe payment settled this
        registration and it carries a payment intent. A plan, an offline
        payment, or more than one payment all return ``None`` — the money is
        the treasurer's to settle, so the console must not offer the choice.
        """
        from payments.models import Payment
        from payments.registration_plans import is_on_plan

        if is_on_plan(self):
            return None
        succeeded = list(self.payments.filter(status=Payment.Status.SUCCEEDED))
        if len(succeeded) != 1:
            return None
        payment = succeeded[0]
        if payment.method != Payment.Method.STRIPE:
            return None
        if not payment.stripe_payment_intent_id:
            return None
        return payment.amount

    @property
    def settled_amount(self):
        """Money already received against this registration, refundable or
        not — what a removal would leave behind if it does not refund."""
        from decimal import Decimal

        from payments.models import Payment
        return sum(
            (p.amount for p in self.payments.filter(
                status=Payment.Status.SUCCEEDED,
            )),
            Decimal("0"),
        )

    @property
    def needs_payment(self) -> bool:
        """Approved (or normal) but unpaid — a Stripe payment is still due."""
        return self.status == self.Status.AWAITING_PAYMENT and self.quoted_amount > 0

    @transaction.atomic
    def approve(self, by):
        """Faculty approves a pending registration. Consumes the pricing code
        (if any), then moves to PAID ($0 / covered) or AWAITING_PAYMENT.
        Returns True if a transition happened."""
        if self.status != self.Status.PENDING_APPROVAL:
            return False
        if self.pricing_code_id:
            from events.models import PricingCode
            PricingCode.objects.filter(
                pk=self.pricing_code_id, max_uses__isnull=False,
            ).update(uses_remaining=F("uses_remaining") - 1)
        # A plan-carrying code splits the fee (task #501). Built here rather
        # than at registration so the schedule starts the day the place is
        # confirmed, not the day it was requested.
        if self.pricing_code_id and self.quoted_amount > 0:
            from payments.registration_plans import build_schedule
            build_schedule(self, self.pricing_code.installments)
        self.approved_by = by
        self.decided_at = timezone.now()
        self.reminded_at = None
        self.status = (
            self.Status.PAID if self.quoted_amount <= 0
            else self.Status.AWAITING_PAYMENT
        )
        self.save(update_fields=(
            "approved_by", "decided_at", "reminded_at", "status",
        ))
        return True

    @transaction.atomic
    def decline(self, by, reason=""):
        """Faculty declines a pending registration. No code/payment side-effects
        (the code was never consumed). Returns True if a transition happened."""
        if self.status != self.Status.PENDING_APPROVAL:
            return False
        self.approved_by = by
        self.decided_at = timezone.now()
        self.decline_reason = reason
        self.reminded_at = None
        self.status = self.Status.DECLINED
        self.save(update_fields=(
            "approved_by", "decided_at", "decline_reason", "reminded_at", "status",
        ))
        return True
