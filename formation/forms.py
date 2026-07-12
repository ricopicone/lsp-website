"""Forms for ongoing formation — the advancement (palimpsest / passage) demande
and the Advisor's recommendation. Application intake forms stay in
``admissions.forms``."""

from __future__ import annotations

from django import forms

from .models import Advancement, ControlAnalysis, ExternalActivity

_INPUT = "input input-bordered w-full"
_TEXTAREA = "textarea textarea-bordered w-full"


class AdvancementForm(forms.ModelForm):
    """A member's demande to advance.

    The demande is an *expression of desire* to present the Palimpsest or
    Passage / Traversée to the whole School at the next Days of Assembly — sent
    to the Advisor in lieu of an email. You don't attach the text you'll
    present; opening the demande is the request itself. The only field is an
    optional note to your Advisor."""

    class Meta:
        model = Advancement
        fields = ("statement",)
        widgets = {
            "statement": forms.Textarea(attrs={"class": _TEXTAREA, "rows": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["statement"].label = "A note to your Advisor (optional)"
        self.fields["statement"].help_text = (
            "Anything you'd like your Advisor to know — they present your "
            "request to the Meeting of the Analysts. You may leave this blank."
        )
        self.fields["statement"].required = False


class RecommendationForm(forms.ModelForm):
    """The Advisor's recommendation + the date they presented the demande to the
    Meeting of the Analysts."""

    class Meta:
        model = Advancement
        fields = ("recommendation", "presented_at")
        widgets = {
            "recommendation": forms.Textarea(attrs={"class": _TEXTAREA, "rows": 6}),
            "presented_at": forms.DateInput(attrs={"type": "date", "class": _INPUT}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["recommendation"].label = "Your recommendation"
        self.fields["recommendation"].help_text = (
            "Your recommendation to the Meeting of the Analysts."
        )
        self.fields["recommendation"].required = True
        self.fields["presented_at"].label = "Date presented to the Meeting"
        self.fields["presented_at"].help_text = (
            "Leave blank to use today's date."
        )
        self.fields["presented_at"].required = False


class ControlAnalysisForm(forms.ModelForm):
    """A member's self-reported control (supervisory) analysis entry — no
    approval, just a personal record toward the control-years target."""

    class Meta:
        model = ControlAnalysis
        fields = ("supervisor_name", "requirement", "modality",
                  "start_date", "end_date", "notes")
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date", "class": _INPUT}),
            "end_date": forms.DateInput(attrs={"type": "date", "class": _INPUT}),
            "supervisor_name": forms.TextInput(attrs={"class": _INPUT}),
            "requirement": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "modality": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "notes": forms.Textarea(attrs={"rows": 3, "class": _TEXTAREA}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["requirement"].label = "Counts toward"
        self.fields["requirement"].help_text = (
            "Tag this as your 4-year control analysis or a 2-year one. "
            "You can change it later."
        )
        self.fields["end_date"].label = "End date"
        self.fields["end_date"].help_text = "Leave blank if this is ongoing."
        self.fields["end_date"].required = False
        self.fields["notes"].required = False


class ExternalActivityForm(forms.ModelForm):
    """A member's self-reported related activity outside LSP (course taken or
    taught, presentation, publication), no approval, just a personal record."""

    class Meta:
        model = ExternalActivity
        fields = ("kind", "title", "venue", "start_date", "end_date", "url", "notes")
        widgets = {
            "kind": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "title": forms.TextInput(attrs={"class": _INPUT}),
            "venue": forms.TextInput(attrs={"class": _INPUT}),
            "start_date": forms.DateInput(attrs={"type": "date", "class": _INPUT}),
            "end_date": forms.DateInput(attrs={"type": "date", "class": _INPUT}),
            "url": forms.URLInput(attrs={"class": _INPUT}),
            "notes": forms.Textarea(attrs={"rows": 3, "class": _TEXTAREA}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["venue"].label = "Venue"
        self.fields["venue"].required = False
        self.fields["end_date"].label = "End date"
        self.fields["end_date"].help_text = "Leave blank if this is a single date or ongoing."
        self.fields["end_date"].required = False
        self.fields["url"].label = "Link"
        self.fields["url"].required = False
        self.fields["notes"].required = False
