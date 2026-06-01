"""Forms for the Workspace surface."""

from __future__ import annotations

from decimal import Decimal

from django import forms

from .models import Workgroup, WorkgroupMeeting


class ReadingGroupTermForm(forms.Form):
    """Open a new annual term for a reading group (date range + per-person fee)."""

    start_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "input input-bordered input-sm"})
    )
    end_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "input input-bordered input-sm"})
    )
    fee = forms.DecimalField(
        min_value=Decimal("0"), max_digits=8, decimal_places=2,
        widget=forms.NumberInput(attrs={"class": "input input-bordered input-sm", "step": "0.01"}),
        help_text="Per-person fee for the year ($0 for a free term).",
    )

    def clean(self):
        data = super().clean()
        start, end = data.get("start_date"), data.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "End date must be on or after the start date.")
        return data


class WorkgroupDatesForm(forms.ModelForm):
    class Meta:
        model = Workgroup
        fields = ("start_date", "end_date")
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date", "class": "input input-bordered"}),
            "end_date": forms.DateInput(attrs={"type": "date", "class": "input input-bordered"}),
        }


class WorkgroupMeetingForm(forms.ModelForm):
    class Meta:
        model = WorkgroupMeeting
        fields = ("title", "starts_at", "ends_at", "location", "note")
        widgets = {
            "title": forms.TextInput(attrs={"class": "input input-bordered input-sm w-full",
                                            "placeholder": "Label (optional)"}),
            "starts_at": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "input input-bordered input-sm"},
                format="%Y-%m-%dT%H:%M",
            ),
            "ends_at": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "input input-bordered input-sm"},
                format="%Y-%m-%dT%H:%M",
            ),
            "location": forms.TextInput(attrs={"class": "input input-bordered input-sm w-full",
                                               "placeholder": "Room or video link"}),
            "note": forms.Textarea(
                attrs={"rows": 2, "class": "textarea textarea-bordered textarea-sm w-full"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # datetime-local inputs submit/display in this format.
        for f in ("starts_at", "ends_at"):
            self.fields[f].input_formats = ["%Y-%m-%dT%H:%M"]
