from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from phonenumber_field.modelfields import PhoneNumberField

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
        PROSPECTIVE_APPLICANT = "prospective_applicant", _("Prospective Applicant")
        STUDENT = "student", _("Student")
        PRE_CANDIDATE = "pre_candidate", _("Pre-Candidate Analyst")
        CANDIDATE = "candidate", _("Candidate Analyst")
        ANALYST = "analyst", _("Analyst")
        PRE_CANDIDATE_SCHOLAR = "pre_candidate_scholar", _("Pre-Candidate Scholar")
        CANDIDATE_SCHOLAR = "candidate_scholar", _("Candidate Scholar")
        SCHOLAR = "scholar", _("Scholar")
        MEMBER = "member", _("Member")
        EXTERNAL = "external", _("Guest")

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
        help_text="Short biographical text. Shown on the directory and on event pages.",
    )
    event_bio = models.TextField(
        blank=True,
        help_text=(
            "Optional alternate bio used when this member is shown as a "
            "speaker on an event page. Falls back to ``bio`` when blank."
        ),
    )
    headshot = models.ImageField(
        upload_to="headshots/%Y/",
        blank=True,
        null=True,
    )
    credentials = models.CharField(
        max_length=200,
        blank=True,
        help_text="Degrees, licenses, board cert (e.g. 'PhD; CA Licensed Psychologist PSY 22767').",
    )
    languages_spoken = models.CharField(
        max_length=200,
        blank=True,
        help_text="Comma-separated languages (e.g. 'English, French, Spanish').",
    )
    location = models.CharField(
        max_length=200,
        blank=True,
        help_text="Free-form city/region/country (e.g. 'Los Gatos, CA, USA').",
    )
    location_lat = models.FloatField(
        null=True,
        blank=True,
        help_text="Latitude geocoded from ``location`` for the Find-an-Analyst map (M11).",
    )
    location_lng = models.FloatField(
        null=True,
        blank=True,
        help_text="Longitude geocoded from ``location``.",
    )
    accepting_patients = models.BooleanField(
        default=True,
        help_text=(
            "Whether this member is currently accepting new patients/analysands. "
            "Drives a pin filter on the Find-an-Analyst map."
        ),
    )
    phone = PhoneNumberField(
        blank=True,
        help_text="Stored in E.164 form. Parsed assuming US if no country code.",
    )
    public_email = models.EmailField(
        blank=True,
        help_text=(
            "Public-facing email for directories / event pages. Distinct from "
            "the login email (User.email) since members often use one address "
            "for their professional listing and another for school correspondence. "
            "Falls back to User.email when unset (see Profile.display_email)."
        ),
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

    @property
    def display_email(self) -> str:
        """Email to show on public pages; falls back to the login email."""
        return self.public_email or self.user.email

    @property
    def display_event_bio(self) -> str:
        """Bio to use when listed as a speaker on an event; falls back to ``bio``."""
        return self.event_bio or self.bio

    #: Roles that appear in the public /directory/ (see accounts.views).
    DIRECTORY_ROLES = frozenset({
        "analyst",
        "candidate",
        "pre_candidate",
        "scholar",
        "candidate_scholar",
        "pre_candidate_scholar",
        "member",
    })

    @property
    def is_in_directory(self) -> bool:
        """Whether this profile appears on /directory/ (drives nav links)."""
        return self.role in self.DIRECTORY_ROLES

    @property
    def directory_slug(self) -> str:
        """URL slug for this profile's /directory/<slug>/ page."""
        return (
            slugify(f"{self.user.first_name} {self.user.last_name}".strip())
            or str(self.user.pk)
        )

    def save(self, *args, **kwargs):
        if not self.is_faculty:
            self.default_billing_mode = None
        super().save(*args, **kwargs)
