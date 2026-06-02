"""Committee charter editing (member-facing manage surface)."""

from __future__ import annotations

from django import forms

from .models import Committee


class CommitteeCharterForm(forms.ModelForm):
    """Edits a committee's public-facing text only — never its name/slug
    (which would orphan the workgroup lookups) or its backing workgroup."""

    class Meta:
        model = Committee
        fields = ["description", "charter"]
        widgets = {
            "description": forms.TextInput(attrs={"class": "input input-bordered w-full"}),
            "charter": forms.Textarea(attrs={
                "rows": 6, "class": "textarea textarea-bordered w-full",
                "placeholder": "What this committee does (markdown supported).",
            }),
        }
