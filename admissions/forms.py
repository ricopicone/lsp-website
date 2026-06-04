"""Forms for the application process — applicant intake + reviewer tools."""

from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model

from accounts.models import Profile

from .models import Advancement, Application, ApplicationInterview

User = get_user_model()

_INPUT = "input input-bordered w-full"
_TEXTAREA = "textarea textarea-bordered w-full"
_SELECT = "select select-bordered w-full"


def analyst_pool():
    """Analysts of the School — the pool interviewers are drawn from."""
    return (
        User.objects.filter(
            is_active=True,
            profile__role=Profile.Role.ANALYST,
            profile__standing=Profile.Standing.ACTIVE,
        )
        .order_by("last_name", "first_name", "email")
    )


class ApplicationForm(forms.ModelForm):
    """Applicant intake. ``track`` is fixed by the URL; the eligibility fields
    adapt to it."""

    class Meta:
        model = Application
        fields = ("background", "eligibility_note", "letter_of_intent", "cv")
        widgets = {
            "background": forms.RadioSelect,
            "eligibility_note": forms.TextInput(attrs={"class": _INPUT}),
            "letter_of_intent": forms.Textarea(attrs={"class": _TEXTAREA, "rows": 10}),
            "cv": forms.ClearableFileInput(
                attrs={"class": "file-input file-input-bordered w-full"}
            ),
        }

    def __init__(self, *args, track=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.track = track
        self.fields["letter_of_intent"].label = "Letter of intent"
        self.fields["letter_of_intent"].help_text = (
            "Your interest and goals in the study of Freudian and Lacanian "
            "psychoanalysis and this formation."
        )
        self.fields["cv"].label = "Curriculum vitae (PDF)"
        self.fields["cv"].required = True
        if track == Application.Track.SCHOLAR:
            del self.fields["background"]
            f = self.fields["eligibility_note"]
            f.label = "Personal Lacanian analysis"
            f.help_text = (
                "Where you began your personal Lacanian analysis (the Scholar "
                "track requires at least one year)."
            )
            f.required = True
        else:
            self.fields["background"].required = True
            f = self.fields["eligibility_note"]
            f.label = "Degree & licensure"
            f.help_text = (
                "Your most advanced degree, and — for a clinical background — "
                "your licensure status."
            )
            f.required = True


class AssignInterviewerForm(forms.Form):
    interviewer = forms.ModelChoiceField(
        queryset=analyst_pool(),
        widget=forms.Select(attrs={"class": _SELECT}),
        label="Add an interviewer (Analyst of the School)",
    )

    def __init__(self, *args, application=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.application = application
        if application is not None:
            already = application.interviews.values_list("interviewer_id", flat=True)
            self.fields["interviewer"].queryset = analyst_pool().exclude(pk__in=already)


class InterviewReportForm(forms.ModelForm):
    class Meta:
        model = ApplicationInterview
        fields = ("completed_at", "report")
        widgets = {
            "completed_at": forms.DateInput(attrs={"type": "date", "class": _INPUT}),
            "report": forms.Textarea(attrs={"class": _TEXTAREA, "rows": 4,
                                             "placeholder": "Report / recommendation"}),
        }


# --- Advancement (palimpsest / passage) ---

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
