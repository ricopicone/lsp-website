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

    Every user has a Profile (auto-created via a post-save signal). ``role``
    is the single source of truth for participation tiers (pricing) and
    members-only access. ``is_faculty`` is an orthogonal axis — a user may
    be faculty *and* a candidate. The faculty-only fields (``bio``,
    ``headshot``, ``default_billing_mode``) live here rather than on a
    sibling model: every user has a Profile anyway, and bio/headshot are
    likely useful for general members in Phase 2.
    """

    class Role(models.TextChoices):
        PROSPECTIVE_APPLICANT = "prospective_applicant", _("Prospective applicant")
        STUDENT = "student", _("Student")
        PRE_CANDIDATE = "pre_candidate", _("Pre-candidate")
        CANDIDATE = "candidate", _("Candidate")
        ANALYST = "analyst", _("Analyst")
        MEMBER = "member", _("Member")
        EXTERNAL = "external", _("External / non-LSP")

    class BillingMode(models.TextChoices):
        PER_CLASS = "per_class", _("Per class")
        PER_SEMINAR = "per_seminar", _("Per seminar")

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
    is_faculty = models.BooleanField(
        default=False,
        help_text="Faculty axis (USR-6). Orthogonal to role.",
    )
    bio = models.TextField(
        blank=True,
        help_text="Short biographical text. Shown on event pages for faculty.",
    )
    headshot = models.ImageField(
        upload_to="headshots/%Y/",
        blank=True,
        null=True,
    )
    default_billing_mode = models.CharField(
        max_length=16,
        choices=BillingMode.choices,
        blank=True,
        null=True,
        help_text="Faculty default for new seminars (REG-6). Null for non-faculty.",
    )
    public = models.BooleanField(
        default=False,
        help_text="Whether to show bio/headshot on public-facing pages.",
    )
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.user.email} ({self.get_role_display()})"

    def save(self, *args, **kwargs):
        if not self.is_faculty:
            self.default_billing_mode = None
        super().save(*args, **kwargs)
