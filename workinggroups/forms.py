"""Working-group creation form (Board-gated, G3)."""

from __future__ import annotations

from django import forms

from cartels.forms import _resolve_member


class WorkingGroupCreateForm(forms.Form):
    name = forms.CharField(
        max_length=120,
        widget=forms.TextInput(attrs={"class": "input input-bordered w-full"}),
        help_text="A short name for the working group.",
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "rows": 4, "class": "textarea textarea-bordered w-full",
            "placeholder": "What is this working group's aim? (markdown supported)",
        }),
    )
    chair = forms.CharField(
        widget=forms.TextInput(attrs={"class": "input input-bordered w-full"}),
        help_text="The chair, as an email or 'First Last' (as in the directory).",
    )
    members = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "class": "textarea textarea-bordered w-full"}),
        help_text="Optional initial members, comma-separated (email or 'First Last').",
    )

    def clean_chair(self):
        user = _resolve_member((self.cleaned_data.get("chair") or "").strip())
        if user is None:
            raise forms.ValidationError(
                "Couldn't find an LSP member matching that chair. Use the exact "
                "email or 'First Last' as in the directory."
            )
        return user

    def clean_members(self):
        raw = (self.cleaned_data.get("members") or "").strip()
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
