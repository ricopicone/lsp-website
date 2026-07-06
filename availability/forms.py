"""Forms for the analyst-availability console."""

from __future__ import annotations

from django import forms

from .models import AvailabilitySettings, ReminderTemplate

_SELECT = forms.Select(attrs={"class": "select select-bordered w-full"})
_TEXT_INPUT = forms.TextInput(attrs={"class": "input input-bordered w-full"})


class AvailabilitySettingsForm(forms.ModelForm):
    class Meta:
        model = AvailabilitySettings
        fields = ["reminder_mode"]
        widgets = {"reminder_mode": _SELECT}


class ReminderTemplateForm(forms.ModelForm):
    class Meta:
        model = ReminderTemplate
        fields = ["subject", "body"]
        widgets = {
            "subject": _TEXT_INPUT,
            "body": forms.Textarea(attrs={
                "rows": 14,
                "class": "textarea textarea-bordered w-full font-sans "
                "text-sm leading-relaxed",
            }),
        }
