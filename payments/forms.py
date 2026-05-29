"""Public forms for dues and donations (REG-12, REG-13)."""

from __future__ import annotations

from decimal import Decimal

from django import forms
from django.db import transaction


class DonationForm(forms.Form):
    """Donation entry — anonymous-friendly.

    Authenticated users: name + email pulled from the User.
    Anonymous users: email is required (for receipt); name is optional.
    """

    amount = forms.DecimalField(
        min_value=Decimal("1.00"),
        max_digits=8,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"step": "1", "style": "width: 6rem;"}),
        help_text="USD.",
    )
    email = forms.EmailField(
        required=False,
        help_text="Where we send your receipt. Required if you're not logged in.",
    )
    name = forms.CharField(
        required=False,
        max_length=200,
        help_text="Optional. Helps us thank you properly.",
    )
    dedication = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Optional. A note about who or what this donation is for.",
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip()
        is_auth = self.user is not None and self.user.is_authenticated
        if not is_auth and not email:
            raise forms.ValidationError(
                "Email is required so we can send your receipt."
            )
        return email


class TuitionDecisionForm(forms.Form):
    """Student-facing tuition decision form (M7.5).

    Captures the three public-facing choices for an in-training student
    each academic year: pay in full, set up a payment plan (treasurer
    follows up to schedule installments), or skip this year. Staff-only
    statuses (EXEMPT, PAID_IN_FULL once the payment actually lands) are
    applied via the admin, not this form.
    """

    STATUS_CHOICES = [
        ("committed",    "I plan to pay tuition for this year."),
        ("payment_plan", "I want to set up a payment plan."),
        ("skipping",     (
            "I'm skipping tuition this year "
            "(I'll pay regular fees for any events I attend)."
        )),
    ]
    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        widget=forms.RadioSelect,
        required=True,
        label="Your decision for this academic year",
    )


class TreasurerSettingsForm(forms.Form):
    """Edit dues + tuition amounts for the current academic-year periods.

    Accepts the periods at construction; renders editable fields for the
    three dues tier amounts and the tuition annual amount. Submitting
    updates both period rows in a single transaction.
    """

    dues_pre_candidate = forms.DecimalField(
        max_digits=8, decimal_places=2, min_value=Decimal("0"),
        label="Pre-candidate dues",
    )
    dues_candidate = forms.DecimalField(
        max_digits=8, decimal_places=2, min_value=Decimal("0"),
        label="Candidate dues",
    )
    dues_analyst = forms.DecimalField(
        max_digits=8, decimal_places=2, min_value=Decimal("0"),
        label="Analyst / Scholar dues",
    )
    tuition_amount = forms.DecimalField(
        max_digits=8, decimal_places=2, min_value=Decimal("0"),
        label="Annual tuition (in-training students)",
    )
    dues_reminder_interval_days = forms.IntegerField(
        min_value=1, max_value=90,
        label="Dues reminder cadence (days)",
        help_text="How often unpaid members are emailed a reminder after the due date.",
    )
    tuition_reminder_interval_days = forms.IntegerField(
        min_value=1, max_value=90,
        label="Tuition reminder cadence (days)",
        help_text="How often undecided / committed-without-payment students are emailed.",
    )

    def __init__(self, *args, dues_period=None, tuition_period=None, **kwargs):
        self.dues_period = dues_period
        self.tuition_period = tuition_period
        initial = kwargs.pop("initial", {}) or {}
        if dues_period is not None:
            initial.setdefault("dues_pre_candidate", dues_period.dues_amount_pre_candidate)
            initial.setdefault("dues_candidate",     dues_period.dues_amount_candidate)
            initial.setdefault("dues_analyst",       dues_period.dues_amount_analyst)
            initial.setdefault(
                "dues_reminder_interval_days",
                dues_period.reminder_interval_days,
            )
        if tuition_period is not None:
            initial.setdefault("tuition_amount", tuition_period.tuition_amount)
            initial.setdefault(
                "tuition_reminder_interval_days",
                tuition_period.reminder_interval_days,
            )
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        # Disable individual fields when their period doesn't exist —
        # treasurer can't edit values for a period that's not configured.
        if dues_period is None:
            for f in ("dues_pre_candidate", "dues_candidate", "dues_analyst",
                      "dues_reminder_interval_days"):
                self.fields[f].disabled = True
                self.fields[f].required = False
        if tuition_period is None:
            for f in ("tuition_amount", "tuition_reminder_interval_days"):
                self.fields[f].disabled = True
                self.fields[f].required = False

    def save(self):
        with transaction.atomic():
            if self.dues_period is not None:
                d = self.dues_period
                d.dues_amount_pre_candidate = self.cleaned_data["dues_pre_candidate"]
                d.dues_amount_candidate     = self.cleaned_data["dues_candidate"]
                d.dues_amount_analyst       = self.cleaned_data["dues_analyst"]
                d.reminder_interval_days    = self.cleaned_data["dues_reminder_interval_days"]
                d.save(update_fields=(
                    "dues_amount_pre_candidate",
                    "dues_amount_candidate",
                    "dues_amount_analyst",
                    "reminder_interval_days",
                ))
            if self.tuition_period is not None:
                t = self.tuition_period
                t.tuition_amount         = self.cleaned_data["tuition_amount"]
                t.reminder_interval_days = self.cleaned_data["tuition_reminder_interval_days"]
                t.save(update_fields=("tuition_amount", "reminder_interval_days"))
