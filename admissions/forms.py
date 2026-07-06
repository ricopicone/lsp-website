"""Forms for the application process — applicant intake + reviewer tools."""

from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model

from accounts.models import Profile

from .models import (
    AdmissionsSettings,
    Application,
    ApplicationInterview,
    MessageTemplate,
)

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


#: Marker shown next to each candidate, by their Application Interviews status.
_AVAIL_MARKER = {
    "yes": "✓ available for interviews",
    "no": "— not available for interviews",
    "unknown": "? availability unknown",
}
_AVAIL_RANK = {"yes": 0, "unknown": 1, "no": 2}


class AssignInterviewerForm(forms.Form):
    interviewer = forms.ModelChoiceField(
        queryset=analyst_pool(),
        widget=forms.Select(attrs={"class": _SELECT}),
        label="Add an interviewer (Analyst of the School)",
    )

    def __init__(self, *args, application=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.application = application
        qs = analyst_pool()
        if application is not None:
            already = application.interviews.values_list("interviewer_id", flat=True)
            qs = qs.exclude(pk__in=already)
            # Sandbox containment: a sandbox application (persona applicant) may
            # only ever involve persona analysts, so the manual-assign override
            # can't pull a real analyst into a training run and email them. A
            # real application excludes personas.
            if application.applicant.profile.is_persona:
                qs = qs.filter(profile__is_persona=True)
            else:
                qs = qs.exclude(profile__is_persona=True)
        self._apply_availability(qs)

    def _apply_availability(self, qs):
        """Order the pool available-first and tag each label with the analyst's
        Application Interviews availability, so the Meeting staffs interviews
        from the coordinator's availability table at a glance."""
        from django.db.models import Case, When

        from availability.services import interview_status_map

        status = interview_status_map(qs.values_list("pk", flat=True))
        ordered = sorted(
            qs,
            key=lambda u: (
                _AVAIL_RANK.get(status.get(u.pk, "unknown"), 1),
                (u.last_name or "").lower(),
                (u.first_name or "").lower(),
            ),
        )
        field = self.fields["interviewer"]
        if ordered:
            field.queryset = qs.order_by(
                Case(*[When(pk=u.pk, then=i) for i, u in enumerate(ordered)])
            )
        else:
            field.queryset = qs

        def _label(user):
            name = user.get_full_name() or user.email
            marker = _AVAIL_MARKER[status.get(user.pk, "unknown")]
            return f"{name}  ·  {marker}"

        field.label_from_instance = _label


class InterviewReportForm(forms.ModelForm):
    class Meta:
        model = ApplicationInterview
        fields = ("completed_at", "report")
        widgets = {
            "completed_at": forms.DateInput(attrs={"type": "date", "class": _INPUT}),
            "report": forms.Textarea(attrs={"class": _TEXTAREA, "rows": 4,
                                             "placeholder": "Report / recommendation"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A report only counts as submitted when it has text; the interview date
        # defaults to today so submitting a report always marks it complete.
        self.fields["report"].required = True
        self.fields["completed_at"].required = False
        self.fields["completed_at"].label = "Interview date"
        self.fields["completed_at"].help_text = "Leave blank for today."

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("completed_at"):
            from django.utils import timezone
            cleaned["completed_at"] = timezone.localdate()
        return cleaned


class AdmissionsSettingsForm(forms.ModelForm):
    class Meta:
        model = AdmissionsSettings
        fields = ("acknowledgment_mode", "invitation_mode")
        widgets = {
            "acknowledgment_mode": forms.Select(attrs={"class": _SELECT}),
            "invitation_mode": forms.Select(attrs={"class": _SELECT}),
        }


class MessageTemplateForm(forms.ModelForm):
    """Edit one of the coordinator's outgoing messages."""

    class Meta:
        model = MessageTemplate
        fields = ("subject", "body")
        widgets = {
            "subject": forms.TextInput(attrs={"class": _INPUT}),
            "body": forms.Textarea(attrs={"class": _TEXTAREA, "rows": 12}),
        }
