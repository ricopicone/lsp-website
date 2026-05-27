"""Forms for the public registration flow."""

from __future__ import annotations

from decimal import Decimal

from django import forms

from events.models import PriceTier, PricingCode
from events.pricing import PricingError, resolve_price


class RegistrationForm(forms.Form):
    """The public-facing registration form for a single event.

    Built with ``event`` and ``user`` kwargs so it can filter tiers to the
    event and resolve pricing against the user. After ``is_valid()``,
    ``cleaned_data["resolution"]`` is a ``PriceResolution`` (amount +
    explanation), and ``cleaned_data["pricing_code_obj"]`` is the
    ``PricingCode`` redeemed (or ``None``).
    """

    price_tier = forms.ModelChoiceField(
        queryset=PriceTier.objects.none(),
        widget=forms.RadioSelect,
        empty_label=None,
    )
    sliding_amount = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        max_digits=8,
        decimal_places=2,
        help_text="If your selected tier is sliding-scale, enter what you'd like to pay.",
    )
    pricing_code = forms.CharField(
        required=False,
        max_length=20,
        help_text="Optional code from faculty.",
    )

    def __init__(self, *args, event=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if event is None or user is None:
            raise TypeError("RegistrationForm requires `event` and `user`.")
        self.event = event
        self.user = user
        self.fields["price_tier"].queryset = PriceTier.objects.filter(
            event=event, session__isnull=True,
        ).order_by("audience")

    def clean(self):
        data = super().clean()
        tier = data.get("price_tier")
        if tier is None:
            return data

        code_str = (data.get("pricing_code") or "").strip().upper()
        code = None
        if code_str:
            try:
                code = PricingCode.objects.get(code=code_str, event=self.event)
            except PricingCode.DoesNotExist:
                self.add_error("pricing_code", "Code not recognized for this event.")
                return data

        try:
            resolution = resolve_price(
                user=self.user,
                tier=tier,
                sliding_amount=data.get("sliding_amount"),
                pricing_code=code,
            )
        except PricingError as exc:
            self.add_error(None, str(exc))
            return data

        data["resolution"] = resolution
        data["pricing_code_obj"] = code
        return data
