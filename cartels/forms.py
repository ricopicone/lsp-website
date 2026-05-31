"""Cartel proposal form (CART-4 step 1)."""

from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from accounts.models import Profile

User = get_user_model()


def _resolve_member(token: str):
    """Resolve an email or 'First Last' to an LSP member User, else None."""
    token = token.strip()
    if not token:
        return None
    qs = User.objects.filter(profile__role__in=Profile.DIRECTORY_ROLES)
    if "@" in token:
        return qs.filter(email__iexact=token).first()
    parts = token.split()
    if len(parts) >= 2:
        first, *_, last = parts
        return qs.filter(first_name__iexact=first, last_name__iexact=last).first()
    return qs.filter(Q(first_name__iexact=token) | Q(last_name__iexact=token)).first()


class CartelProposalForm(forms.Form):
    name = forms.CharField(
        max_length=120,
        widget=forms.TextInput(attrs={"class": "input input-bordered w-full"}),
        help_text="A short name for the cartel.",
    )
    guiding_question = forms.CharField(
        widget=forms.Textarea(attrs={
            "rows": 2, "class": "textarea textarea-bordered w-full",
            "placeholder": "The question the cartel forms around",
        }),
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "rows": 4, "class": "textarea textarea-bordered w-full",
            "placeholder": "What is this cartel about? (markdown supported)",
        }),
    )
    invitees = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "class": "textarea textarea-bordered w-full"}),
        help_text="Optional: members to invite specially, comma-separated "
        "(email or 'First Last').",
    )

    def clean_invitees(self):
        raw = (self.cleaned_data.get("invitees") or "").strip()
        if not raw:
            return []
        users, unmatched = [], []
        for token in [t for t in (s.strip() for s in raw.split(",")) if t]:
            u = _resolve_member(token)
            if u is None:
                unmatched.append(token)
            elif u not in users:
                users.append(u)
        if unmatched:
            raise forms.ValidationError(
                "Couldn't find LSP members matching: "
                + ", ".join(repr(t) for t in unmatched)
                + ". Use the exact email or 'First Last' as in the directory."
            )
        return users
