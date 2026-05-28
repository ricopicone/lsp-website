"""Public forms for dues and donations (REG-12, REG-13)."""

from __future__ import annotations

from decimal import Decimal

from django import forms


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
