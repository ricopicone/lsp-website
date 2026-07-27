"""Forms for the application process — applicant intake + reviewer tools."""

from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import BaseUserManager

from accounts.membership import academic_year_label, current_academic_year_start
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


class DirectAdmitForm(forms.Form):
    """Admit a member who never applied on the site (task #476).

    Lives in the Web Coordinator's admin, not the Applications Coordinator's
    console: someone who applied here is admitted from their application, and
    the two surfaces are deliberately kept apart. The guard below is the
    structural half of that — an email belonging to any application, in any
    status, is refused outright rather than offered an override.
    """

    SEND_LETTER = "letter"
    SEND_ACCOUNT = "account"
    SEND_NONE = "none"
    SEND_CHOICES = [
        (SEND_ACCOUNT, "Account-ready invitation, they've already been welcomed"),
        (SEND_LETTER, "Full acceptance letter, they've heard nothing yet"),
        (SEND_NONE, "Nothing, I'll write to them myself"),
    ]

    email = forms.EmailField(
        label="Email", widget=forms.EmailInput(attrs={"class": _INPUT}),
    )
    first_name = forms.CharField(
        label="First name", max_length=150,
        widget=forms.TextInput(attrs={"class": _INPUT}),
    )
    last_name = forms.CharField(
        label="Last name", max_length=150,
        widget=forms.TextInput(attrs={"class": _INPUT}),
    )
    track = forms.ChoiceField(
        label="Formation", choices=Application.Track.choices,
        widget=forms.Select(attrs={"class": _SELECT}),
    )
    formation_background = forms.ChoiceField(
        label="Background", required=False,
        choices=[("", "Not yet reviewed")] + [
            (v, label) for v, label in Profile.FormationBackground.choices
            if v != Profile.FormationBackground.UNREVIEWED
        ],
        widget=forms.Select(attrs={"class": _SELECT}),
        help_text="Determines the control-analysis requirement. Leave unreviewed "
                  "if the Meeting of Analysts hasn't determined it.",
    )
    effective_ay = forms.TypedChoiceField(
        label="Effective academic year", coerce=int, choices=[],
        widget=forms.Select(attrs={"class": _SELECT}),
        help_text="The year their membership starts.",
    )
    note = forms.CharField(
        label="Note", required=False,
        widget=forms.Textarea(attrs={"class": _TEXTAREA, "rows": 3}),
        help_text="Recorded on the membership timeline, and included in the "
                  "acceptance letter if you send one.",
    )
    send = forms.ChoiceField(
        label="Send", choices=SEND_CHOICES, initial=SEND_ACCOUNT,
        widget=forms.RadioSelect(attrs={"class": "radio radio-sm"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.existing_user = None
        current = current_academic_year_start()
        # The upcoming AY is offered as well: someone admitted over the summer
        # is usually joining for the year about to start, and
        # ``academic_year_choices`` stops at the current one.
        self.fields["effective_ay"].choices = [
            (y, academic_year_label(y)) for y in range(current + 1, current - 6, -1)
        ]
        self.fields["effective_ay"].initial = current

    def clean_email(self) -> str:
        email = BaseUserManager.normalize_email(self.cleaned_data["email"]).strip()
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            return email
        application = Application.objects.filter(applicant=user).first()
        if application is not None:
            raise forms.ValidationError(
                f"{email} applied through the site "
                f"({application.get_status_display().lower()}). Admit them from "
                "their application in the Applications Coordinator's console, "
                "not here."
            )
        self.existing_user = user
        return email
