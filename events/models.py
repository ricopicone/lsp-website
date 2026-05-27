"""Events, sessions, pricing tiers, and faculty-issued pricing codes.

Implements the core data model for Milestone 2:

- ``Event`` — a seminar or special event (PROG-1, PROG-4).
- ``Session`` — an individual meeting within an event; per-class billing
  (REG-6) and the unified calendar (PROG-6) hang off this.
- ``PriceTier`` — the conditional-pricing rules (REG-3, REG-4, REG-5, REG-6).
- ``PricingCode`` — faculty escape hatch for alternate pricing (REG-17).
"""

from __future__ import annotations

import secrets
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

# Excludes visually ambiguous characters (0/O, 1/I/L).
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generate_pricing_code() -> str:
    """Generate a short, human-friendly pricing code."""
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))


class Event(models.Model):
    class Type(models.TextChoices):
        SEMINAR = "seminar", _("Seminar")
        SPECIAL_EVENT = "special_event", _("Special event")

    class Format(models.TextChoices):
        ONLINE = "online", _("Online")
        IN_PERSON = "in_person", _("In person")
        HYBRID = "hybrid", _("Hybrid")

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        OPEN = "open", _("Open for registration")
        CLOSED = "closed", _("Closed")

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    description = models.TextField(
        blank=True,
        help_text="Editable by faculty for events they teach (PROG-7).",
    )
    event_type = models.CharField(
        max_length=20,
        choices=Type.choices,
        default=Type.SEMINAR,
    )
    faculty = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="events_taught",
        blank=True,
        limit_choices_to={"profile__is_faculty": True},
        help_text="Instructors. Restricted to users marked is_faculty (USR-6).",
    )
    start_date = models.DateField()
    end_date = models.DateField()
    format = models.CharField(
        max_length=20,
        choices=Format.choices,
        default=Format.ONLINE,
    )
    access_info = models.TextField(
        blank=True,
        help_text="Zoom link or similar. Released to registrants only after payment (REG-8).",
    )
    registration_opens = models.DateTimeField(null=True, blank=True)
    registration_closes = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    published = models.BooleanField(
        default=False,
        help_text="Whether the public event page is visible (PROG-1).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-start_date", "title")

    def __str__(self):
        return self.title

    def clean(self):
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "end_date must be on or after start_date."})


class Session(models.Model):
    """A single meeting within an event — calendar's unit of display.

    Sessions are typically generated in bulk by the recurrence helper
    (PROG-5) and then independently editable so a single date can move
    without re-running the pattern.
    """

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="sessions")
    title = models.CharField(max_length=200, blank=True)
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    location = models.CharField(
        max_length=200,
        blank=True,
        help_text="Room name or address for in-person/hybrid sessions.",
    )
    sequence = models.PositiveIntegerField(
        default=0,
        help_text="Stable ordering within an event.",
    )

    class Meta:
        ordering = ("event", "sequence", "start_at")
        indexes = [models.Index(fields=["start_at"])]

    def __str__(self):
        label = self.title or f"Session {self.sequence}"
        return f"{self.event.title} — {label} ({self.start_at.date().isoformat()})"

    def clean(self):
        if self.end_at and self.start_at and self.end_at <= self.start_at:
            raise ValidationError({"end_at": "end_at must be after start_at."})


class Audience(models.TextChoices):
    """Pricing audience — Profile.Role values plus ``all``."""

    ALL = "all", _("All")
    PROSPECTIVE_APPLICANT = "prospective_applicant", _("Prospective applicant")
    STUDENT = "student", _("Student")
    PRE_CANDIDATE = "pre_candidate", _("Pre-candidate")
    CANDIDATE = "candidate", _("Candidate")
    ANALYST = "analyst", _("Analyst")
    MEMBER = "member", _("Member")
    EXTERNAL = "external", _("External / non-LSP")


class PriceTier(models.Model):
    """A price for an event (or a single session) keyed to an audience."""

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="price_tiers")
    session = models.ForeignKey(
        Session,
        on_delete=models.CASCADE,
        related_name="price_tiers",
        null=True,
        blank=True,
        help_text="Set only for per-class pricing (REG-6).",
    )
    audience = models.CharField(
        max_length=32,
        choices=Audience.choices,
        default=Audience.ALL,
    )
    base_amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        help_text="Listed price in USD.",
    )
    sliding_scale = models.BooleanField(
        default=False,
        help_text="If true, the payer may choose any amount at or above minimum_amount (REG-5).",
    )
    minimum_amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Floor for sliding-scale tiers; 0 expresses 'none turned away'.",
    )
    covered_by_tuition = models.BooleanField(
        default=False,
        help_text="Tuition-paying members in this audience owe nothing (REG-4).",
    )

    class Meta:
        ordering = ("event", "session", "audience")

    def __str__(self):
        scope = f"session {self.session_id}" if self.session_id else "event"
        return f"{self.event.title} / {self.get_audience_display()} ({scope}): ${self.base_amount}"

    def clean(self):
        if self.sliding_scale and self.minimum_amount is None:
            raise ValidationError(
                {"minimum_amount": "minimum_amount is required when sliding_scale is true."}
            )
        if (
            self.minimum_amount is not None
            and self.minimum_amount > self.base_amount
        ):
            raise ValidationError(
                {"minimum_amount": "minimum_amount cannot exceed base_amount."}
            )


class PricingCode(models.Model):
    """A faculty-issued alternate-pricing token for an event (REG-17)."""

    class Mode(models.TextChoices):
        PERCENT_OFF = "percent_off", _("Percent off")
        FIXED_AMOUNT = "fixed_amount", _("Fixed amount")
        SLIDING_FLOOR = "sliding_floor", _("Sliding-scale floor")

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="pricing_codes")
    code = models.CharField(max_length=20, unique=True, db_index=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="pricing_codes_issued",
        help_text="Faculty member who minted the code.",
    )
    pricing_mode = models.CharField(max_length=20, choices=Mode.choices)
    amount_or_percent = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        help_text=(
            "Interpreted per pricing_mode: percent_off → 0–100 (percent), "
            "fixed_amount → USD price, sliding_floor → USD minimum."
        ),
    )
    valid_until = models.DateTimeField(null=True, blank=True)
    max_uses = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Null = unlimited.",
    )
    uses_remaining = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Decremented on successful redemption. Null when max_uses is null.",
    )
    restricted_to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pricing_codes_eligible",
        help_text="When set, only that user can redeem.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.code} ({self.event.title})"

    def save(self, *args, **kwargs):
        if not self.code:
            # Retry on the unlikely collision; the alphabet/length give ~10^11 combos.
            for _attempt in range(5):
                candidate = generate_pricing_code()
                if not PricingCode.objects.filter(code=candidate).exists():
                    self.code = candidate
                    break
            else:
                raise RuntimeError("Could not generate a unique pricing code after 5 attempts.")
        if self.uses_remaining is None and self.max_uses is not None:
            self.uses_remaining = self.max_uses
        super().save(*args, **kwargs)

    def clean(self):
        if self.pricing_mode == self.Mode.PERCENT_OFF and not (
            Decimal("0") <= self.amount_or_percent <= Decimal("100")
        ):
            raise ValidationError(
                {"amount_or_percent": "percent_off requires a value between 0 and 100."}
            )
        if self.amount_or_percent < 0:
            raise ValidationError({"amount_or_percent": "Cannot be negative."})

    def is_redeemable(self, *, user=None, now=None) -> bool:
        """True if this code can currently be redeemed (optionally by ``user``)."""
        from django.utils import timezone

        now = now or timezone.now()
        if self.valid_until and now > self.valid_until:
            return False
        if self.max_uses is not None and (self.uses_remaining or 0) <= 0:
            return False
        if (
            self.restricted_to_user_id
            and user is not None
            and user.pk != self.restricted_to_user_id
        ):
            return False
        # Faculty must be active on this event (issued_by still in Event.faculty).
        return True
