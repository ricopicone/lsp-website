"""Forms for the Workspace surface."""

from __future__ import annotations

from django import forms

from .models import Workgroup, WorkgroupMeeting


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
