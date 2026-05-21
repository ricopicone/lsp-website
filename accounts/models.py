from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _

from .managers import UserManager


class User(AbstractUser):
    """Custom user model: login is by email address rather than username."""

    username = None
    email = models.EmailField(_("email address"), unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.email


class Profile(models.Model):
    """LSP-specific data attached to each user.

    The ``role`` is the single source of truth for participation tiers
    (pricing) and members-only access. A profile is created automatically
    for every user via a post-save signal.
    """

    class Role(models.TextChoices):
        PROSPECTIVE_APPLICANT = "prospective_applicant", _("Prospective applicant")
        STUDENT = "student", _("Student")
        PRE_CANDIDATE = "pre_candidate", _("Pre-candidate")
        CANDIDATE = "candidate", _("Candidate")
        ANALYST = "analyst", _("Analyst")
        MEMBER = "member", _("Member")
        EXTERNAL = "external", _("External / non-LSP")

    user = models.OneToOneField(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="profile",
    )
    role = models.CharField(
        max_length=32,
        choices=Role.choices,
        default=Role.EXTERNAL,
        help_text="LSP standing; drives event pricing and members-only access.",
    )
    tuition_paying = models.BooleanField(
        default=False,
        help_text="Whether this member pays tuition (affects seminar pricing).",
    )
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.user.email} ({self.get_role_display()})"
