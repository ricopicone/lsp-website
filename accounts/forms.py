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
    """Find-an-Analyst inquiry submitted by a visitor (M11).

    The handler emails the Referral Coordinator with the submitted fields;
    Reply-To is set to the submitter's address so a coordinator's reply
    reaches the inquirer.
    """

    MODALITY_CHOICES = [
        ("in_person", "In-person"),
        ("remote",    "Remote (phone or video)"),
        ("either",    "Either is fine"),
    ]

    name = forms.CharField(
        max_length=120, required=True, label="Your name",
    )
    email = forms.EmailField(
        required=True, label="Email",
        help_text="The coordinator will reply to this address.",
    )
    phone = forms.CharField(
        max_length=40, required=False, label="Phone (optional)",
    )
    location = forms.CharField(
        max_length=200, required=True, label="Where are you?",
        help_text="City, state or region, country.",
    )
    preferred_languages = forms.CharField(
        max_length=120, required=False, label="Preferred language(s)",
        help_text="Optional. List one or more, in any order.",
    )
    modality = forms.ChoiceField(
        choices=MODALITY_CHOICES, widget=forms.RadioSelect,
        required=True, label="Preferred modality",
    )
    inquiry = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 5}),
        required=True, label="What are you looking for?",
        help_text=(
            "A few sentences about what brings you to this inquiry — "
            "what you're hoping the coordinator can help with."
        ),
    )
    additional_notes = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False, label="Anything else? (optional)",
    )
    # Honeypot — humans don't see it; bots fill it. Reject if non-empty.
    website = forms.CharField(
        required=False, widget=forms.HiddenInput(),
    )

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("Bot detected.")
        return ""
