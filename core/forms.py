"""Forms for the core control panel."""

from __future__ import annotations

from django import forms

from .models import Aphorism


class AphorismForm(forms.ModelForm):
    class Meta:
        model = Aphorism
        fields = ["quote", "short_attribution", "full_attribution", "is_active"]
        widgets = {
            "quote": forms.Textarea(attrs={"rows": 3}),
            "full_attribution": forms.Textarea(attrs={"rows": 2}),
        }
        labels = {
            "short_attribution": "Attribution (chip)",
            "full_attribution": "Full attribution (tooltip)",
            "is_active": "Active",
        }
