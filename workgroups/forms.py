"""Forms for the Workspace surface."""

from __future__ import annotations

from decimal import Decimal

from django import forms

from .models import MeetingSeries, Workgroup, WorkgroupMeeting

_INPUT = "input input-bordered input-sm w-full"
_DT = {"type": "datetime-local", "class": "input input-bordered input-sm"}
_DATE = {"type": "date", "class": "input input-bordered input-sm"}
_TIME = {"type": "time", "class": "input input-bordered input-sm"}
_TA = "textarea textarea-bordered textarea-sm w-full"


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
        fields = ("title", "starts_at", "ends_at", "location", "online_url",
                  "access_info", "note")
        widgets = {
            "title": forms.TextInput(attrs={"class": _INPUT, "placeholder": "Label (optional)"}),
            "starts_at": forms.DateTimeInput(attrs=_DT, format="%Y-%m-%dT%H:%M"),
            "ends_at": forms.DateTimeInput(attrs=_DT, format="%Y-%m-%dT%H:%M"),
            "location": forms.TextInput(attrs={"class": _INPUT, "placeholder": "Room or place"}),
            "online_url": forms.URLInput(attrs={"class": _INPUT, "placeholder": "Video-call link"}),
            "access_info": forms.TextInput(
                attrs={"class": _INPUT, "placeholder": "Passcode / dial-in"}),
            "note": forms.Textarea(attrs={"rows": 2, "class": _TA}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in ("starts_at", "ends_at"):
            self.fields[f].input_formats = ["%Y-%m-%dT%H:%M"]


_WEEKDAY_CHOICES = [
    ("MO", "Mon"), ("TU", "Tue"), ("WE", "Wed"), ("TH", "Thu"),
    ("FR", "Fri"), ("SA", "Sat"), ("SU", "Sun"),
]


class MeetingSeriesForm(forms.ModelForm):
    """Create a recurring meeting series (weekly / biweekly / monthly-ordinal)."""

    weekdays = forms.MultipleChoiceField(
        choices=_WEEKDAY_CHOICES, widget=forms.CheckboxSelectMultiple,
        help_text="Which day(s) of the week.",
    )

    class Meta:
        model = MeetingSeries
        fields = ("title", "frequency", "weekdays", "week_position",
                  "start_date", "end_date", "start_time", "end_time",
                  "location", "online_url", "access_info", "description")
        widgets = {
            "title": forms.TextInput(attrs={"class": _INPUT, "placeholder": "Label (optional)"}),
            "frequency": forms.Select(attrs={"class": "select select-bordered select-sm"}),
            "week_position": forms.Select(attrs={"class": "select select-bordered select-sm"}),
            "start_date": forms.DateInput(attrs=_DATE),
            "end_date": forms.DateInput(attrs=_DATE),
            "start_time": forms.TimeInput(attrs=_TIME),
            "end_time": forms.TimeInput(attrs=_TIME),
            "location": forms.TextInput(attrs={"class": _INPUT, "placeholder": "Room or place"}),
            "online_url": forms.URLInput(attrs={"class": _INPUT, "placeholder": "Video-call link"}),
            "access_info": forms.TextInput(
                attrs={"class": _INPUT, "placeholder": "Passcode / dial-in"}),
            "description": forms.Textarea(attrs={"rows": 2, "class": _TA}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["week_position"] = forms.TypedChoiceField(
            coerce=int, choices=[(1, "First"), (2, "Second"), (3, "Third"),
                                 (4, "Fourth"), (-1, "Last")],
            widget=forms.Select(attrs={"class": "select select-bordered select-sm"}),
            required=False, initial=1,
            help_text="Which week of the month (monthly only).",
        )

    def clean(self):
        data = super().clean()
        data["weekdays"] = ",".join(data.get("weekdays") or [])
        sd, ed = data.get("start_date"), data.get("end_date")
        if sd and ed and ed < sd:
            self.add_error("end_date", "End date must be on or after the start date.")
        st, et = data.get("start_time"), data.get("end_time")
        if st and et and et <= st:
            self.add_error("end_time", "End time must be after the start time.")
        return data


class MeetingMinutesForm(forms.ModelForm):
    class Meta:
        model = WorkgroupMeeting
        fields = ("minutes",)
        widgets = {"minutes": forms.Textarea(
            attrs={"rows": 8, "class": "textarea textarea-bordered w-full",
                   "placeholder": "Minutes / notes…"})}


class MeetingRescheduleForm(forms.ModelForm):
    class Meta:
        model = WorkgroupMeeting
        fields = ("starts_at", "ends_at")
        widgets = {
            "starts_at": forms.DateTimeInput(attrs=_DT, format="%Y-%m-%dT%H:%M"),
            "ends_at": forms.DateTimeInput(attrs=_DT, format="%Y-%m-%dT%H:%M"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in ("starts_at", "ends_at"):
            self.fields[f].input_formats = ["%Y-%m-%dT%H:%M"]
