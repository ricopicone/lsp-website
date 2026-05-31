"""Forms for the Workspace surface."""

from __future__ import annotations

from django import forms

from .models import Workgroup


class WorkgroupDatesForm(forms.ModelForm):
    class Meta:
        model = Workgroup
        fields = ("start_date", "end_date")
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date", "class": "input input-bordered"}),
            "end_date": forms.DateInput(attrs={"type": "date", "class": "input input-bordered"}),
        }
