"""Forms for a member's private meeting room (task #687)."""
from __future__ import annotations

from django import forms

from .models import PersonalRoom

_INPUT = "input input-bordered w-full"
_SELECT = "select select-bordered w-full"


class PersonalRoomSettingsForm(forms.ModelForm):
    """Recording and office hours, the two things the member controls."""

    class Meta:
        model = PersonalRoom
        fields = ("recording_mode", "office_hours", "hours_note", "waiting_room")
        widgets = {
            "recording_mode": forms.Select(attrs={"class": _SELECT}),
            "office_hours": forms.Select(attrs={"class": _SELECT}),
            "hours_note": forms.TextInput(attrs={
                "class": _INPUT,
                "placeholder": "Thursdays 3-4pm Pacific",
            }),
            "waiting_room": forms.CheckboxInput(attrs={"class": "checkbox checkbox-sm"}),
        }
        labels = {
            "recording_mode": "Recording",
            "office_hours": "Office hours",
            "hours_note": "When (or how to arrange it)",
            "waiting_room": "Let people in one at a time",
        }
        help_texts = {
            "hours_note": (
                "Shown to members on your directory page, and to the students of "
                "any seminar or reading group you lead."
            ),
        }

    def clean(self):
        data = super().clean()
        # Advertising nothing is the same as not advertising: rather than reject
        # the pair, say what is missing, since the member plainly meant to post.
        if data.get("office_hours") != PersonalRoom.OfficeHours.OFF and not (
            data.get("hours_note") or ""
        ).strip():
            self.add_error("hours_note", "Add a line saying when, or how to arrange a time.")
        return data
