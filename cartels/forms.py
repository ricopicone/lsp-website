"""Cartel start/proposal forms (task #392)."""

from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from accounts.models import Profile

User = get_user_model()


def _resolve_member(token: str):
    """Resolve an email or 'First Last' to an LSP directory member, else None.

    Kept here as a shared helper (also used by ``workinggroups.forms``)."""
    token = (token or "").strip()
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
    """Shared cartel-details form (used for editing a cartel's details).

    ``invitees`` is a set of directory members supplied by the people-picker
    widget (removable chips → hidden ``invitees`` inputs carrying user PKs)."""

    name = forms.CharField(
        max_length=120,
        widget=forms.TextInput(attrs={"class": "input input-bordered w-full"}),
        help_text="A short name for the cartel.",
    )
    theme = forms.CharField(
        widget=forms.Textarea(attrs={
            "rows": 2, "class": "textarea textarea-bordered w-full",
            "placeholder": "The theme the cartel forms around",
        }),
    )
    description = forms.CharField(
        required=False,
        label="Further description",
        widget=forms.Textarea(attrs={
            "rows": 4, "class": "textarea textarea-bordered w-full",
            "placeholder": "Anything more about this cartel (optional, markdown supported)",
        }),
    )
    invitees = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),
        required=False,
        widget=forms.MultipleHiddenInput,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["invitees"].queryset = User.objects.filter(
            profile__role__in=Profile.DIRECTORY_ROLES
        )


class CartelStartForm(CartelProposalForm):
    """The start (propose) form: adds the invitation-only toggle. Kept off the
    plain edit form so editing a cartel's details can't silently reopen it."""

    closed = forms.BooleanField(
        required=False,
        label="Invitation only, closed to members outside the invited list",
        widget=forms.CheckboxInput(attrs={"class": "checkbox checkbox-sm"}),
    )
