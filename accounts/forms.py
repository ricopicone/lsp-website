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
