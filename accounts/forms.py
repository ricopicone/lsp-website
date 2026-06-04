"""Forms for the email-based custom user model.

``UserCreationForm`` / ``UserChangeForm`` back the Django admin.
``LightSignupForm`` is the public-facing signup form used in the
registration flow (architecture § 6.1 — "lightweight signup at the start
of the flow").
"""

from django import forms
from django.conf import settings
from django.contrib.auth.forms import BaseUserCreationForm, PasswordResetForm
from django.contrib.auth.forms import UserChangeForm as BaseUserChangeForm
from django.core.mail import EmailMultiAlternatives
from django.template import loader

from .models import Profile, User


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
            "public_phone",
            "website",
            "specialties",
            "consultation_modalities",
            "year_joined",
            "public",
            "accepting_patients",
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

    #: Per-field visibility <select> name prefix for a TOGGLEABLE_PUBLIC_FIELDS key.
    VIS_PREFIX = "vis_"

    def __init__(self, *args, **kwargs):
        from django.utils import timezone as dj_timezone

        from .models import TOGGLEABLE_PUBLIC_FIELDS, Profile

        super().__init__(*args, **kwargs)

        self.fields["consultation_modalities"].choices = Profile.Modality.choices
        if self.instance and self.instance.pk:
            self.initial["consultation_modalities"] = self.instance.modalities_list

        # phonenumber widgets need the shared input styling applied by hand.
        for name in ("phone", "public_phone"):
            self.fields[name].widget.attrs.setdefault("class", _INPUT)
            self.fields[name].widget.attrs.setdefault("placeholder", "+1 555 555 5555")

        # year_joined as a friendly descending dropdown (harvest accelerator).
        this_year = dj_timezone.now().year
        years = [("", "—")] + [(y, f"AY {y}–{y + 1}") for y in range(this_year, 1979, -1)]
        self.fields["year_joined"].widget = forms.Select(
            attrs={"class": _SELECT}, choices=years
        )

        for name in ("public", "accepting_patients"):
            self.fields[name].widget.attrs.setdefault("class", "toggle toggle-primary")

        # One visibility <select> (Public / Members only / Private) per
        # toggleable field, initialised from the member's field_visibility map.
        # Only meaningful for directory-eligible members (others aren't shown
        # publicly), so skip them — that also keeps save() from clobbering the
        # map for non-directory users.
        directory = bool(self.instance.pk and self.instance.is_in_directory)
        self._vis_keys = TOGGLEABLE_PUBLIC_FIELDS if directory else ()
        if directory:
            current = self.instance.field_visibility or {}
            for key in TOGGLEABLE_PUBLIC_FIELDS:
                self.fields[self.VIS_PREFIX + key] = forms.ChoiceField(
                    required=False,
                    choices=Profile.Visibility.choices,
                    initial=current.get(key, Profile.Visibility.PUBLIC),
                    widget=forms.Select(
                        attrs={"class": "select select-xs select-bordered",
                               "aria-label": "Visibility"}
                    ),
                )

    def clean_consultation_modalities(self):
        # MultipleChoiceField yields a list; the model field is a CSV string.
        return ",".join(self.cleaned_data.get("consultation_modalities") or [])

    def save(self, commit=True):
        from .models import Profile

        profile = super().save(commit=False)
        # Collect the per-field visibility <select>s into field_visibility.
        # Skip when not rendered (non-directory member) so we don't clobber it.
        if self._vis_keys:
            profile.field_visibility = {
                key: (self.cleaned_data.get(self.VIS_PREFIX + key)
                      or Profile.Visibility.PUBLIC)
                for key in self._vis_keys
            }
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


class MembershipChangeForm(forms.Form):
    """Board record-keeping: a member's new role + standing, effective AY, and
    the decision note. Drives :func:`accounts.membership.record_membership_change`."""

    role = forms.ChoiceField(
        choices=Profile.Role.choices,
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    standing = forms.ChoiceField(
        choices=Profile.Standing.choices,
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    effective_ay = forms.IntegerField(
        min_value=1980, max_value=2100,
        label="Effective academic year (start year)",
        help_text="e.g. 2026 for AY 2026–2027.",
        widget=forms.NumberInput(attrs={"class": "input input-bordered w-full"}),
    )
    notes = forms.CharField(
        required=False, label="Decision / note",
        widget=forms.Textarea(attrs={
            "rows": 2, "class": "textarea textarea-bordered w-full",
            "placeholder": "e.g. Board minutes 2026-05-12",
        }),
    )


class AdvisorSelectForm(forms.Form):
    """An in-training member picks their Advisor from the eligible pool."""

    advisor = forms.ModelChoiceField(
        queryset=User.objects.none(),
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
        label="Your advisor",
    )

    def __init__(self, *args, advisee=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.advisee = advisee
        if advisee is not None:
            from .advisor import eligible_advisors
            self.fields["advisor"].queryset = eligible_advisors(advisee)
        self.fields["advisor"].label_from_instance = lambda u: (
            f"{u.get_full_name() or u.email} — {u.profile.get_role_display()}"
        )


class ReplyToPasswordResetForm(PasswordResetForm):
    """Django's password-reset form, but with ``Reply-To: SUPPORT_EMAIL``.

    Matches the rest of the app's transactional mail (see
    ``accounts.emails``) so a member who replies to the reset email reaches
    support, not the no-reply sending address.
    """

    def send_mail(self, subject_template_name, email_template_name, context,
                  from_email, to_email, html_email_template_name=None):
        subject = loader.render_to_string(subject_template_name, context)
        subject = "".join(subject.splitlines())  # email subjects are single-line
        body = loader.render_to_string(email_template_name, context)
        msg = EmailMultiAlternatives(
            subject, body, from_email, [to_email],
            reply_to=[settings.SUPPORT_EMAIL],
        )
        if html_email_template_name is not None:
            html = loader.render_to_string(html_email_template_name, context)
            msg.attach_alternative(html, "text/html")
        msg.send()


class MagicLinkRequestForm(forms.Form):
    """Ask for a passwordless sign-in link by email address."""

    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={
            "class": _INPUT, "autocomplete": "email", "autofocus": True,
        }),
    )

    def clean_email(self) -> str:
        from django.contrib.auth.models import BaseUserManager
        return BaseUserManager.normalize_email(self.cleaned_data["email"]).strip()


class TOTPCodeForm(forms.Form):
    """A code entry — a 6-digit TOTP, or a backup recovery code at challenge.

    Validation of the code against the device happens in the view (it needs
    the device); this just collects and lightly normalises the input.
    """

    code = forms.CharField(
        label="Code",
        max_length=20,
        widget=forms.TextInput(attrs={
            "class": _INPUT,
            "autocomplete": "one-time-code",
            "inputmode": "numeric",
            "autofocus": True,
            "placeholder": "123456",
        }),
    )

    def clean_code(self) -> str:
        return (self.cleaned_data.get("code") or "").strip()


class IntakeSurveyForm(forms.Form):
    """Scalar fields of the launch intake survey. The year-grid checkboxes are
    parsed from POST separately (see ``accounts.survey.parse_grid``)."""

    year_joined = forms.IntegerField(
        required=False, min_value=1970, max_value=2100,
        label="Roughly what year did you join LSP?",
        widget=forms.NumberInput(attrs={"class": _INPUT, "placeholder": "e.g. 2019"}),
    )
    pronouns = forms.CharField(
        required=False, max_length=80, label="Pronouns (optional)",
        widget=forms.TextInput(attrs={"class": _INPUT}),
    )
    payment_names = forms.CharField(
        required=False, max_length=255,
        label="Other name on your payments",
        widget=forms.TextInput(attrs={"class": _INPUT, "placeholder": "optional"}),
    )
    payment_emails = forms.CharField(
        required=False, max_length=255,
        label="Other email (Stripe / PayPal)",
        widget=forms.TextInput(attrs={"class": _INPUT, "placeholder": "optional"}),
    )
    list_in_directory = forms.BooleanField(
        required=False,
        label="List me in the public member directory (name, role, bio, photo).",
        widget=forms.CheckboxInput(attrs={"class": "checkbox checkbox-sm"}),
    )
