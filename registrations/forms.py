"""Forms for the public registration flow."""

from __future__ import annotations

from decimal import Decimal

from django import forms

from events.models import PriceTier, PricingCode
from events.pricing import PricingError, resolve_price


class _TierChoiceField(forms.ModelChoiceField):
    """Format the radio option label cleanly per tier shape."""

    def label_from_instance(self, obj: PriceTier) -> str:
        audience = obj.get_audience_display()
        if obj.covered_by_tuition:
            return f"{audience} — Included in tuition for tuition-paying members"
        if obj.sliding_scale:
            floor = obj.minimum_amount if obj.minimum_amount is not None else Decimal("0")
            return (
                f"{audience} — Sliding scale "
                f"(suggested ${obj.base_amount}, minimum ${floor})"
            )
        return f"{audience} — ${obj.base_amount}"


class RegistrationForm(forms.Form):
    """The public-facing registration form for a single event.

    Built with ``event`` and ``user`` kwargs so it can filter tiers to the
    event and resolve pricing against the user. The user's role-matching
    tier is pre-selected; ``cleaned_data["resolution"]`` holds the
    ``PriceResolution`` (amount + explanation) after ``is_valid()``.
    """

    price_tier = _TierChoiceField(
        queryset=PriceTier.objects.none(),
        widget=forms.RadioSelect,
        empty_label=None,
    )
    sliding_amount = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        max_digits=8,
        decimal_places=2,
        help_text=(
            "Required when the selected tier is sliding-scale, or when a "
            "sliding-floor pricing code is applied."
        ),
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

        # Pre-select the user's role-matching tier, falling back to 'all'.
        role = getattr(getattr(user, "profile", None), "role", None)
        if role:
            initial = self.fields["price_tier"].queryset.filter(audience=role).first()
            if initial is None:
                initial = self.fields["price_tier"].queryset.filter(audience="all").first()
            if initial is not None:
                self.fields["price_tier"].initial = initial.pk

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
