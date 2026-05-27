"""Forms for the events app (PROG-7, PROG-8)."""

from __future__ import annotations

from decimal import Decimal

from django import forms

from .models import Event, PricingCode


class EventDescriptionForm(forms.ModelForm):
    """Faculty-facing edit form for the event description (PROG-7)."""

    class Meta:
        model = Event
        fields = ("description",)
        widgets = {
            "description": forms.Textarea(attrs={"rows": 12, "cols": 80}),
        }


class PricingCodeForm(forms.ModelForm):
    """Faculty-issued pricing code (PROG-8 / REG-17)."""

    class Meta:
        model = PricingCode
        fields = (
            "pricing_mode",
            "amount_or_percent",
            "valid_until",
            "max_uses",
            "restricted_to_user",
        )
        widgets = {
            "valid_until": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M",
            ),
        }

    def clean(self):
        data = super().clean()
        mode = data.get("pricing_mode")
        amount = data.get("amount_or_percent")
        if mode == PricingCode.Mode.PERCENT_OFF and amount is not None and not (
            Decimal("0") <= amount <= Decimal("100")
        ):
            self.add_error("amount_or_percent", "percent_off requires a value between 0 and 100.")
        if amount is not None and amount < 0:
            self.add_error("amount_or_percent", "Cannot be negative.")
        return data
