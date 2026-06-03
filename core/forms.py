"""Forms for the core control panel."""

from __future__ import annotations

from django import forms
from django.utils.text import slugify

from committees.models import Committee

from .models import Aphorism

_INPUT = "input input-bordered w-full"
_TEXTAREA = "textarea textarea-bordered w-full"


class CommitteeForm(forms.ModelForm):
    """Create / edit a committee. Saving a new one auto-builds its backing
    workgroup (see ``Committee.save``). The slug is set once from the name and
    not editable here — changing it would orphan the committee's workspace."""

    class Meta:
        model = Committee
        fields = ["name", "description", "charter", "public"]
        widgets = {
            "name": forms.TextInput(attrs={"class": _INPUT}),
            "description": forms.TextInput(attrs={"class": _INPUT}),
            "charter": forms.Textarea(attrs={"class": _TEXTAREA, "rows": 4}),
        }
        help_texts = {
            "public": "Give this committee a public page.",
        }

    def save(self, commit=True):
        committee = super().save(commit=False)
        if not committee.slug:
            base = slugify(committee.name)[:90] or "committee"
            slug, n = base, 2
            while Committee.objects.filter(slug=slug).exclude(pk=committee.pk).exists():
                slug = f"{base}-{n}"
                n += 1
            committee.slug = slug
        if commit:
            committee.save()
        return committee


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
