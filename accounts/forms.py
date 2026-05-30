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


# Shared Tailwind/DaisyUI input classes so the profile editor matches the
# rest of the site without per-widget fiddling.
_INPUT = "input input-bordered w-full"
_TEXTAREA = "textarea textarea-bordered w-full"
_SELECT = "select select-bordered w-full"


class EmailChangeForm(forms.Form):
    """Initiate a login-email change: new address + current-password re-auth.

    Validates that the new address is well-formed, different from the
    current one, and not already taken by another account. The actual
    switch happens only after the new address is verified (see the
    ``email_change_confirm`` view), so this just gates the request.
    """

    new_email = forms.EmailField(
        label="New login email",
        widget=forms.EmailInput(attrs={"class": _INPUT, "autocomplete": "email"}),
    )
    password = forms.CharField(
        label="Current password",
        strip=False,
        widget=forms.PasswordInput(attrs={"class": _INPUT, "autocomplete": "current-password"}),
        help_text="For your security, confirm your password to change your login email.",
    )

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        password = self.cleaned_data.get("password", "")
        if not self.user.check_password(password):
            raise forms.ValidationError("That password is incorrect.")
        return password

    def clean_new_email(self):
        from django.contrib.auth.models import BaseUserManager

        from .models import User

        email = BaseUserManager.normalize_email(self.cleaned_data["new_email"]).strip()
        if email.lower() == self.user.email.lower():
            raise forms.ValidationError("That's already your login email.")
        if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError("An account with that email already exists.")
        return email


class UserNameForm(forms.ModelForm):
    """The name fields that live on User (the rest of the editor is Profile)."""

    class Meta:
        model = User
        fields = ("first_name", "last_name")
        widgets = {
            "first_name": forms.TextInput(attrs={"class": _INPUT}),
            "last_name": forms.TextInput(attrs={"class": _INPUT}),
        }


class ProfileEditForm(forms.ModelForm):
    """Self-service profile editor (every field a member may set themselves).

    Excludes the staff-controlled axes (``role``, ``is_faculty``) and the
    derived geocode fields — those stay in the admin. ``headshot`` is handled
    separately in the view via the cropper pipeline. ``location`` changes
    trigger a re-geocode (see :meth:`save`).
    """

    consultation_modalities = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="How you meet analysands",
        help_text="Shown on Find-an-Analyst.",
    )
    # Declared explicitly so a scheme-less entry ("example.org") becomes a
    # valid https URL (the Django 6.0 default), without the global setting.
    website = forms.URLField(
        required=False,
        assume_scheme="https",
        widget=forms.URLInput(attrs={"class": _INPUT, "placeholder": "https://"}),
    )

    class Meta:
        from .models import Profile
        from .timezones import LSP_TIMEZONES
        model = Profile
        fields = (
            "display_name",
            "pronouns",
            "bio",
            "event_bio",
            "credentials",
            "languages_spoken",
            "location",
            "phone",
            "public_email",
            "website",
            "specialties",
            "consultation_modalities",
            "year_joined",
            "accepting_patients",
            "public",
            "default_billing_mode",
            "timezone",
        )
        widgets = {
            "display_name": forms.TextInput(attrs={"class": _INPUT}),
            "pronouns": forms.TextInput(
                attrs={"class": _INPUT, "placeholder": "she/her"}
            ),
            "bio": forms.Textarea(attrs={"class": _TEXTAREA, "rows": 6}),
            "event_bio": forms.Textarea(attrs={"class": _TEXTAREA, "rows": 4}),
            "credentials": forms.TextInput(attrs={"class": _INPUT}),
            "languages_spoken": forms.TextInput(
                attrs={"class": _INPUT, "placeholder": "English, French"}
            ),
            "location": forms.TextInput(
                attrs={"class": _INPUT, "placeholder": "Los Gatos, CA, USA"}
            ),
            "public_email": forms.EmailInput(attrs={"class": _INPUT}),
            "website": forms.URLInput(
                attrs={"class": _INPUT, "placeholder": "https://"}
            ),
            "specialties": forms.Textarea(attrs={"class": _TEXTAREA, "rows": 3}),
            "default_billing_mode": forms.Select(attrs={"class": _SELECT}),
            # NB: ``website`` is declared on the form (assume_scheme), not here.
            "timezone": forms.Select(
                attrs={"class": _SELECT},
                choices=[("", "Use Pacific Time (project default)")] + LSP_TIMEZONES,
            ),
        }

    def __init__(self, *args, **kwargs):
        from django.utils import timezone as dj_timezone

        from .models import Profile

        super().__init__(*args, **kwargs)

        self.fields["consultation_modalities"].choices = Profile.Modality.choices
        if self.instance and self.instance.pk:
            self.initial["consultation_modalities"] = self.instance.modalities_list

        # phonenumber widget needs the shared input styling applied by hand.
        self.fields["phone"].widget.attrs.setdefault("class", _INPUT)
        self.fields["phone"].widget.attrs.setdefault("placeholder", "+1 555 555 5555")

        # year_joined as a friendly descending dropdown (harvest accelerator).
        this_year = dj_timezone.now().year
        years = [("", "—")] + [(y, f"AY {y}–{y + 1}") for y in range(this_year, 1979, -1)]
        self.fields["year_joined"].widget = forms.Select(
            attrs={"class": _SELECT}, choices=years
        )

        for name in ("public", "accepting_patients"):
            self.fields[name].widget.attrs.setdefault("class", "toggle toggle-primary")

    def clean_consultation_modalities(self):
        # MultipleChoiceField yields a list; the model field is a CSV string.
        return ",".join(self.cleaned_data.get("consultation_modalities") or [])

    def save(self, commit=True):
        profile = super().save(commit=False)
        # If the member edited their location, stale the geocode so the next
        # `geocode_profiles` run (which only touches rows with no coords)
        # re-resolves pins. See accounts/management/commands/geocode_profiles.py.
        if "location" in self.changed_data:
            profile.location_lat = None
            profile.location_lng = None
            profile.location_pins = []
        if commit:
            profile.save()
        return profile
