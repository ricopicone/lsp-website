"""Forms for ongoing formation — the advancement (palimpsest / passage) demande
and the Advisor's recommendation. Application intake forms stay in
``admissions.forms``."""

from __future__ import annotations

from django import forms

from accounts.models import Profile, User

from .models import Advancement, ControlAnalysis, ExternalActivity, ExternalControlAnalyst

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
    approval, just a personal record toward the control-years target.

    The analyst is chosen from a School dropdown (active, public analysts),
    a previously-approved external analyst of the member's own, or typed in
    as a fallback name; ``clean()`` caches the chosen analyst's display name
    onto ``supervisor_name``."""

    school_analyst = forms.ModelChoiceField(
        queryset=User.objects.none(), required=False,
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
        label="Analyst of the School",
        help_text="Choose from the School's analysts, or request an external "
                  "analyst below.",
    )
    external_analyst = forms.ModelChoiceField(
        queryset=ExternalControlAnalyst.objects.none(), required=False,
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
        label="Approved external analyst",
    )

    class Meta:
        model = ControlAnalysis
        fields = ("school_analyst", "external_analyst", "supervisor_name",
                  "requirement", "modality", "start_date", "end_date", "notes")
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date", "class": _INPUT}),
            "end_date": forms.DateInput(attrs={"type": "date", "class": _INPUT}),
            "supervisor_name": forms.TextInput(attrs={"class": _INPUT}),
            "requirement": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "modality": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "notes": forms.Textarea(attrs={"rows": 3, "class": _TEXTAREA}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["school_analyst"].queryset = (
            User.objects.filter(
                profile__role=Profile.Role.ANALYST,
                profile__public=True,
                profile__standing=Profile.Standing.ACTIVE,
                is_active=True,
            ).order_by("last_name", "first_name")
        )
        if user is not None:
            self.fields["external_analyst"].queryset = (
                ExternalControlAnalyst.objects.filter(
                    member=user, status=ExternalControlAnalyst.Status.APPROVED)
            )
        self.fields["requirement"].label = "Counts toward"
        self.fields["requirement"].help_text = (
            "Tag this as your 4-year control analysis or a 2-year one. "
            "You can change it later."
        )
        self.fields["supervisor_name"].label = "Or type a name"
        self.fields["supervisor_name"].help_text = (
            "Only if the analyst is not selectable above."
        )
        self.fields["supervisor_name"].required = False
        self.fields["end_date"].label = "End date"
        self.fields["end_date"].help_text = "Leave blank if this is ongoing."
        self.fields["end_date"].required = False
        self.fields["notes"].required = False

    def clean(self):
        cleaned = super().clean()
        school = cleaned.get("school_analyst")
        external = cleaned.get("external_analyst")
        typed = (cleaned.get("supervisor_name") or "").strip()
        if not (school or external or typed):
            raise forms.ValidationError(
                "Choose a School analyst, an approved external analyst, or type a name.")
        # Cache a display name.
        if school:
            cleaned["supervisor_name"] = school.get_full_name() or school.email
        elif external:
            cleaned["supervisor_name"] = external.name
        return cleaned


class ExternalControlAnalystForm(forms.ModelForm):
    """A member's request to authorize an analyst outside the School for
    control (supervisory) analysis. Decided by the Meeting of the Analysts."""

    class Meta:
        model = ExternalControlAnalyst
        fields = ("name", "email", "phone", "description")
        widgets = {
            "name": forms.TextInput(attrs={"class": _INPUT}),
            "email": forms.EmailInput(attrs={"class": _INPUT}),
            "phone": forms.TextInput(attrs={"class": _INPUT}),
            "description": forms.Textarea(attrs={"rows": 4, "class": _TEXTAREA}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = False
        self.fields["phone"].required = False
        self.fields["description"].label = "About this analyst"
        self.fields["description"].help_text = (
            "Who they are and why you're requesting them, including their "
            "qualifications."
        )


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
