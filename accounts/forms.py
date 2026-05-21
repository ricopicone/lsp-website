"""Admin forms for the email-based custom user model."""

from django.contrib.auth.forms import BaseUserCreationForm
from django.contrib.auth.forms import UserChangeForm as BaseUserChangeForm

from .models import User


class UserCreationForm(BaseUserCreationForm):
    """Create a user from an email address and password."""

    class Meta(BaseUserCreationForm.Meta):
        model = User
        fields = ("email",)


class UserChangeForm(BaseUserChangeForm):
    """Edit an existing user in the admin."""

    class Meta(BaseUserChangeForm.Meta):
        model = User
        fields = "__all__"
