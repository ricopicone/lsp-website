"""Payments, receipts, and the dues lifecycle (architecture § 5.5, REG-12)."""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.models import Source  # provenance flag, shared with MembershipTenure


class DuesPeriod(models.Model):
    """An academic year's dues cycle (REG-12).

    Dues are tiered by role: pre-candidates, candidates, and analysts/
    scholars each pay a different amount per year, set per period. Use
    :meth:`amount_for_role` to resolve the right tier for a given user.
    Use :meth:`current` to find the period covering today.
    """

    name = models.CharField(max_length=100, unique=True, help_text="e.g. AY 2026–2027")
    slug = models.SlugField(max_length=100, unique=True)
    start_date = models.DateField(help_text="First day of the academic year.")
    due_date = models.DateField(help_text="Payment due by this date.")
    end_date = models.DateField(help_text="Last day of the academic year.")
    dues_amount_pre_candidate = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        help_text="Amount owed by pre-candidates (analyst or scholar track).",
    )
    dues_amount_candidate = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        help_text="Amount owed by candidates (analyst or scholar track).",
    )
    dues_amount_analyst = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        help_text="Amount owed by full Analysts and Scholars.",
    )
    block_registration_when_unpaid = models.BooleanField(
        default=False,
        help_text=(
            "Future flag — not currently enforced. When True, the registration "
            "view will refuse event registrations from obligated unpaid users."
        ),
    )
    reminder_interval_days = models.PositiveSmallIntegerField(
        default=7,
        help_text=(
            "How often to email reminders to unpaid members after the due date."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    #: Maps Profile.role values to the tier-field name on this model.
    ROLE_TO_TIER = {
        "pre_candidate":         "dues_amount_pre_candidate",
        "pre_candidate_scholar": "dues_amount_pre_candidate",
        "candidate":             "dues_amount_candidate",
        "candidate_scholar":     "dues_amount_candidate",
        "analyst":               "dues_amount_analyst",
        "scholar":               "dues_amount_analyst",
    }

    class Meta:
        ordering = ("-start_date",)

    def __str__(self):
        return self.name

    @classmethod
    def current(cls, on_date=None):
        """Return the DuesPeriod containing ``on_date`` (default today), or None."""
        on = on_date or timezone.now().date()
        return cls.objects.filter(start_date__lte=on, end_date__gte=on).first()

    def amount_for_role(self, role: str):
        """Return the dues amount owed by a user with the given Profile.role.

        Roles outside ``ROLE_TO_TIER`` (e.g. ``member``, ``external``) return
        None — meaning the role isn't dues-obligated under the tiered model.
        """
        field = self.ROLE_TO_TIER.get(role)
        return getattr(self, field) if field else None


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
        TUITION = "tuition", _("Tuition")

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
    livemode = models.BooleanField(
        default=True,
        db_index=True,
        help_text="False for Stripe *test*-mode payments — kept out of real "
        "accounting. Offline/manual and live payments are True.",
    )
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
    tuition_installment = models.ForeignKey(
        "payments.TuitionInstallment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payments",
        help_text="The tuition installment this payment satisfies — set for type=TUITION.",
    )
    tuition_period = models.ForeignKey(
        "payments.TuitionPeriod",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payments",
        help_text="The academic year a tuition payment is for, when assigned "
        "directly (overrides the date-based attribution; e.g. an August payment "
        "the member assigns to a specific AY).",
    )
    split_from = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="split_parts",
        help_text="Set on the sibling rows created when a payment is split "
        "across categories; the parent row keeps the Stripe identifiers and "
        "the receipt. Refunding any part refunds the whole original charge.",
    )
    notes = models.TextField(blank=True, help_text="Staff notes — e.g. for offline payments.")
    member_note = models.TextField(
        blank=True,
        help_text="A note the member wrote about this payment (visible to the treasurer).",
    )
    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.STAFF,
        db_index=True,
        help_text="Provenance — how this record entered the system.",
    )
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
    def transaction_date(self):
        """The date the payment actually happened, for display and sorting.

        ``created_at`` is ``auto_now_add`` — the row-insertion time, which for
        imported historical payments is the *import* date, not the payment
        date. ``paid_at`` holds the real payment date (set by the Stripe
        webhook / offline-apply, or by the ledger/Stripe imports). Fall back to
        ``created_at`` only when a payment has no ``paid_at`` yet (pending /
        failed). Ordering querysets should use
        ``Coalesce("paid_at", "created_at")`` to match this. (Task #437.)
        """
        return self.paid_at or self.created_at

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


# ---------------------------------------------------------------------------
# Tuition lifecycle (M7.5 — see ../LSP-Website-Phase2-Plan.md)
#
# Students in the four in-training roles (pre_candidate / candidate / scholar
# variants) must pay 4 total years of tuition before transitioning to full
# Analyst / Scholar. The years don't have to be contiguous. Per-year status is
# tracked on TuitionEnrollment; the legacy Profile.tuition_paying boolean is
# kept temporarily for migration but is_tuition_current() is the source of
# truth.
# ---------------------------------------------------------------------------


class TuitionPeriod(models.Model):
    """An academic year's tuition cycle.

    Mirrors :class:`DuesPeriod` but for student tuition. Decisions and
    payments are scoped to a period; ``current()`` returns the period
    covering today (or None).
    """

    name = models.CharField(max_length=100, unique=True, help_text="e.g. AY 2026–2027")
    slug = models.SlugField(max_length=100, unique=True)
    start_date = models.DateField(help_text="First day of the academic year.")
    decision_due_date = models.DateField(
        help_text=(
            "By this date students should have committed to pay / "
            "pay in installments / skip."
        ),
    )
    payment_due_date = models.DateField(
        null=True, blank=True,
        help_text=(
            "Tuition payment due by this date (unpaid-committed reminders "
            "escalate after it; decision reminders key off decision_due_date)."
        ),
    )
    end_date = models.DateField(help_text="Last day of the academic year.")
    tuition_amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        help_text="Annual tuition owed by an enrolled student.",
    )
    reminder_interval_days = models.PositiveSmallIntegerField(
        default=7,
        help_text=(
            "How often to email reminders to students with no decision / "
            "unpaid committed status, after the decision-due date."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-start_date",)

    def __str__(self):
        return self.name

    @classmethod
    def current(cls, on_date=None):
        """Return the TuitionPeriod containing ``on_date`` (default today), or None."""
        on = on_date or timezone.now().date()
        return cls.objects.filter(start_date__lte=on, end_date__gte=on).first()

    @classmethod
    def upcoming(cls, on_date=None):
        """Return the earliest period whose start_date is after ``on_date``
        (default today), or None. Distinct from ``current()`` — a period
        already underway is not "upcoming"."""
        on = on_date or timezone.now().date()
        return cls.objects.filter(start_date__gt=on).order_by("start_date").first()

    def clean(self):
        if self.payment_due_date and self.payment_due_date < self.decision_due_date:
            raise ValidationError(
                {"payment_due_date": "payment_due_date cannot be before decision_due_date."}
            )


class TuitionEnrollment(models.Model):
    """A student's per-year tuition decision and status.

    Replaces the single ``Profile.tuition_paying`` boolean. A row exists
    once a student records a decision for the period; absence of a row
    means "no decision yet" (treated as not-current for blocking checks
    and not-covered for the REG-4 pricing path).
    """

    class Status(models.TextChoices):
        # Order matches the lifecycle: undecided -> committed -> paying -> paid.
        # Skipping is allowed; permanent exemption is not — students owe four
        # total years of tuition before transitioning out of in-training roles.
        COMMITTED = "committed", _("Committed (will pay)")
        PAYMENT_PLAN = "payment_plan", _("On payment plan")
        PAID_IN_FULL = "paid_in_full", _("Paid in full")
        SKIPPING = "skipping", _("Skipping this year")
        PLAN_REQUESTED = "plan_requested", _("Payment plan requested")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tuition_enrollments",
    )
    tuition_period = models.ForeignKey(
        TuitionPeriod,
        on_delete=models.PROTECT,
        related_name="enrollments",
    )
    status = models.CharField(max_length=20, choices=Status.choices)
    decided_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, help_text="Staff notes — overrides, special arrangements.")
    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.STAFF,
        db_index=True,
        help_text="Provenance — how this enrollment record entered the system.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "tuition_period"),
                name="payments_unique_user_per_tuition_period",
            ),
        ]
        ordering = ("-tuition_period__start_date", "user__last_name")

    def __str__(self):
        return f"{self.user} → {self.tuition_period} ({self.get_status_display()})"

    @property
    def covers_seminars(self) -> bool:
        """True when this enrollment grants 'covered by tuition' pricing.

        SKIPPING does not cover — the student opted out of tuition this
        year and pays the regular per-event fee.
        """
        return self.status in {
            self.Status.COMMITTED,
            self.Status.PAYMENT_PLAN,
            self.Status.PAID_IN_FULL,
        }


class TuitionPlanApplication(models.Model):
    """A student's request to the Board for a tuition payment plan
    (task #450 phase B).

    A student may have at most one PENDING application per
    (user, tuition_period) at a time — the partial unique constraint below
    enforces that — but a DECLINED (or APPROVED) application doesn't block a
    later resubmission for the same period.
    """

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        APPROVED = "approved", _("Approved")
        DECLINED = "declined", _("Declined")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tuition_plan_applications",
    )
    tuition_period = models.ForeignKey(
        TuitionPeriod,
        on_delete=models.PROTECT,
        related_name="plan_applications",
    )
    reasons = models.TextField(
        help_text="The student's stated reasons for requesting a payment plan.",
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True, help_text="Board's decision note, if any.")

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("user", "tuition_period"),
                condition=Q(status="pending"),
                name="one_pending_plan_application",
            ),
        ]

    def __str__(self):
        return f"{self.user} → {self.tuition_period} ({self.get_status_display()})"


class TuitionInstallment(models.Model):
    """One installment of a payment-plan tuition enrollment.

    Scaffold — MVP supports manual treasurer-marked payments. Auto-charging
    via Stripe Subscriptions is a Phase 2 enhancement. ``paid`` is the
    boolean of record; ``payments`` (reverse) holds the linked Payment row(s)
    when the treasurer applies one.
    """

    enrollment = models.ForeignKey(
        TuitionEnrollment,
        on_delete=models.CASCADE,
        related_name="installments",
    )
    sequence = models.PositiveSmallIntegerField(help_text="1-indexed order within the plan.")
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    paid = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("enrollment", "sequence")
        constraints = [
            models.UniqueConstraint(
                fields=("enrollment", "sequence"),
                name="payments_unique_installment_sequence",
            ),
        ]

    def __str__(self):
        return f"{self.enrollment} #{self.sequence} due {self.due_date}"

    def mark_paid(self, *, save=True) -> None:
        if self.paid:
            return
        self.paid = True
        if self.paid_at is None:
            self.paid_at = timezone.now()
        if save:
            self.save(update_fields=("paid", "paid_at"))


class TuitionReminder(models.Model):
    """One row per tuition-decision / payment reminder email sent.

    Mirrors :class:`DuesReminder` — drives the weekly throttle for the
    September+ reminder cron.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tuition_reminders",
    )
    tuition_period = models.ForeignKey(
        TuitionPeriod,
        on_delete=models.CASCADE,
        related_name="reminders",
    )
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-sent_at",)
        indexes = [models.Index(fields=("user", "tuition_period", "-sent_at"))]

    def __str__(self):
        return f"{self.user} ← {self.tuition_period} @ {self.sent_at.isoformat()}"


class Charge(models.Model):
    """A debit line in a member's unified account (task #439).

    The credit side is the existing :class:`Payment`. Balance and per-charge
    coverage are *derived* in :mod:`payments.ledger` — one pot of money swept
    across OPEN charges oldest-first; never a per-payment allocation.
    """

    class Category(models.TextChoices):
        DUES = "dues", _("Dues")
        TUITION = "tuition", _("Tuition")
        REGISTRATION = "registration", _("Registration")

    class Status(models.TextChoices):
        OPEN = "open", _("Open")            # counts toward the obligation
        WAIVED = "waived", _("Waived")      # treasurer forgave — audit only
        VOID = "void", _("Void")            # cancelled/superseded — audit only

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="charges",
    )
    category = models.CharField(max_length=20, choices=Category.choices)
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    currency = models.CharField(max_length=3, default="usd")
    effective_date = models.DateField(
        help_text="Orders the oldest-first coverage sweep — AY start for "
        "dues/tuition, settle date for registrations.",
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True,
    )
    dues_period = models.ForeignKey(
        DuesPeriod, on_delete=models.PROTECT, null=True, blank=True,
        related_name="charges",
    )
    tuition_period = models.ForeignKey(
        TuitionPeriod, on_delete=models.PROTECT, null=True, blank=True,
        related_name="charges",
    )
    registration = models.ForeignKey(
        "registrations.Registration", on_delete=models.PROTECT, null=True,
        blank=True, related_name="charges",
    )
    source = models.CharField(
        max_length=20, choices=Source.choices, default=Source.STAFF,
        db_index=True, help_text="Provenance — how this charge entered the system.",
    )
    staff_adjusted = models.BooleanField(
        default=False,
        help_text="Set when a treasurer edits this row; the minting syncs "
        "then never touch it (disagreements surface on the Reconcile tab).",
    )
    notes = models.TextField(blank=True, help_text="Append-only audit trail.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("effective_date", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "dues_period"),
                condition=models.Q(dues_period__isnull=False) & ~models.Q(status="void"),
                name="charge_unique_user_dues_period",
            ),
            models.UniqueConstraint(
                fields=("user", "tuition_period"),
                condition=models.Q(tuition_period__isnull=False) & ~models.Q(status="void"),
                name="charge_unique_user_tuition_period",
            ),
            models.UniqueConstraint(
                fields=("registration",),
                condition=models.Q(registration__isnull=False) & ~models.Q(status="void"),
                name="charge_unique_registration",
            ),
        ]
        indexes = [models.Index(fields=("user", "status"))]

    def __str__(self):
        return (
            f"${self.amount} {self.get_category_display().lower()} charge "
            f"({self.get_status_display()}, {self.user})"
        )

    def add_note(self, text: str, *, save=True) -> None:
        """Append a dated line to the audit trail."""
        line = f"[{timezone.now().date()}] {text}"
        self.notes = (self.notes + "\n" + line) if self.notes else line
        if save:
            self.save(update_fields=("notes",))


class LedgerSubmission(models.Model):
    """A member's claim of a missing historical payment or charge (task #439).

    Crucial for students who started before the site's records begin — a
    member reports "I paid $2,000 tuition in 2019" and the treasurer approves
    (minting the matching :class:`Payment`/:class:`Charge`, honor-system era,
    ``source=SELF_REPORTED``) or declines it from the Reconcile queue's
    Member submissions section. See docs/superpowers/specs/
    2026-07-16-member-account-v2-design.md §3.
    """

    class Kind(models.TextChoices):
        PAYMENT = "payment", _("Payment (I paid this)")
        CHARGE = "charge", _("Charge (I owed this)")

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        APPROVED = "approved", _("Approved")
        DECLINED = "declined", _("Declined")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ledger_submissions",
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    category = models.CharField(
        max_length=20,
        choices=Payment.Type.choices,
        help_text="Payment.Type values for a payment claim; dues/tuition/"
        "registration (Charge.Category) for a charge claim.",
    )
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    claimed_date = models.DateField(help_text="When the member says this happened.")
    details = models.TextField(help_text="The member's account of what this was.")
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True,
    )
    decision_note = models.TextField(blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ledger_submissions_decided",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    created_payment = models.ForeignKey(
        Payment, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    created_charge = models.ForeignKey(
        Charge, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return (f"{self.get_kind_display()} claim: ${self.amount} "
                f"({self.get_status_display()}, {self.user})")


class PaymentMemberAction(models.Model):
    """One statement action a member took on their *own* payment (task #443).

    Members have full treasurer parity on their own payments — re-categorize,
    split (donation flips included, which can raise ``tuition_years_covered``
    and self-clear the promotion gate), and note. Those changes are visible in
    the provenance hover but otherwise passive; this row is the treasurer's
    active surface for them, driving a "member-changed payments" review queue
    on the Reconcile tab. It's an append-only audit log — never edited, never
    read back into ledger math — so no cross-references beyond the FK.
    """

    class Action(models.TextChoices):
        RETYPE = "retype", _("Re-categorized")
        SPLIT = "split", _("Split")
        NOTE = "note", _("Note")

    payment = models.ForeignKey(
        Payment, on_delete=models.CASCADE, related_name="member_actions",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="payment_member_actions",
    )
    action = models.CharField(max_length=10, choices=Action.choices)
    summary = models.CharField(
        max_length=200,
        help_text="Human-readable one-liner, e.g. 'Tuition → Donation'.",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.get_action_display()} ${self.payment_id} by {self.user}"
