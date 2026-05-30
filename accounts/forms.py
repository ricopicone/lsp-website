"""Forms for the email-based custom user model.

``UserCreationForm`` / ``UserChangeForm`` back the Django admin.
``LightSignupForm`` is the public-facing signup form used in the
registration flow (architecture § 6.1 — "lightweight signup at the start
of the flow").
"""

from django import forms
from django.contrib.auth.forms import BaseUserCreationForm
from django.contrib.auth.forms import UserChangeForm as BaseUserChangeForm

from .models import User


class UserCreationForm(BaseUserCreationForm):
    """Create a user from an email address and password (admin)."""

    class Meta(BaseUserCreationForm.Meta):
        model = User
        fields = ("email",)


class UserChangeForm(BaseUserChangeForm):
    """Edit an existing user in the admin."""

    class Meta(BaseUserChangeForm.Meta):
        model = User
        fields = "__all__"


class LightSignupForm(BaseUserCreationForm):
    """Public signup form: email, optional name, password."""

    first_name = forms.CharField(required=False, max_length=150)
    last_name = forms.CharField(required=False, max_length=150)

    class Meta(BaseUserCreationForm.Meta):
        model = User
        fields = ("email", "first_name", "last_name")


class ReferralRequestForm(forms.Form):
    """Find-an-Analyst inquiry — fields mirror the Wix Typeform exactly."""

    PRONOUN_CHOICES = [
        ("she/her",   "she/her"),
        ("he/him",    "he/him"),
        ("they/them", "they/them"),
        ("other",     "Other"),
    ]
    MODALITY_CHOICES = [
        ("in_person", "In person"),
        ("phone",     "By phone"),
        ("video",     "By online video platform"),
    ]

    name = forms.CharField(
        max_length=120, required=True, label="What is your name?",
    )
    pronouns = forms.ChoiceField(
        choices=PRONOUN_CHOICES, widget=forms.RadioSelect,
        required=True, label="What pronouns do you use?",
    )
    pronouns_other = forms.CharField(
        max_length=80, required=False, label="Other pronouns",
        help_text="Only fill this in if you chose Other above.",
    )
    email = forms.EmailField(
        required=True,
        label="What email address would you like to use for the referral process?",
    )
    location = forms.CharField(
        max_length=200, required=True,
        label=(
            "In what city and state (if in the United States) or city and "
            "country (if outside of the United States) are you located?"
        ),
    )
    language = forms.CharField(
        max_length=80, required=True,
        label="What language would you prefer to work in?",
    )
    modality = forms.MultipleChoiceField(
        choices=MODALITY_CHOICES, widget=forms.CheckboxSelectMultiple,
        required=True,
        label="How would you like to meet?",
        help_text=(
            "You can select more than one option. If you are only interested "
            "in meeting in person, please first consult the map on this page "
            "to see if there are any available clinicians in your area."
        ),
    )
    additional_information = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 7}),
        required=True,
        label="Anything else for the Referral Coordinator",
        help_text=(
            "This space is for you to share any other information you would "
            "like the Referral Coordinator to distribute to your potential "
            "Analyst. You may want to share what you are hoping to work on, "
            "how you came to an interest in psychoanalysis, or if you have "
            "been in therapy or analysis before. Please do not include any "
            "identifying information such as your name or email in this "
            "section."
        ),
    )
    # Honeypot — humans don't see it; bots fill it. Reject if non-empty.
    website = forms.CharField(required=False, widget=forms.HiddenInput())

    def clean_pronouns_other(self):
        v = (self.cleaned_data.get("pronouns_other") or "").strip()
        if self.cleaned_data.get("pronouns") == "other" and not v:
            raise forms.ValidationError(
                "Please specify your pronouns since you selected Other."
            )
        return v

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("Bot detected.")
        return ""

    def pronouns_display(self) -> str:
        """Pronouns formatted for the coordinator email (resolves "other")."""
        choice = self.cleaned_data.get("pronouns")
        if choice == "other":
            return self.cleaned_data.get("pronouns_other") or "Other"
        return choice or ""


class TimezoneForm(forms.ModelForm):
    """Per-user timezone picker (Profile.timezone)."""

    class Meta:
        from .models import Profile
        from .timezones import LSP_TIMEZONES
        model = Profile
        fields = ("timezone",)
        widgets = {
            "timezone": forms.Select(
                choices=[("", "Use Pacific Time (project default)")] + LSP_TIMEZONES,
            ),
        }
