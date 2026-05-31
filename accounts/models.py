import secrets
from datetime import timedelta

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from phonenumber_field.modelfields import PhoneNumberField

from .managers import UserManager


def _email_change_token() -> str:
    """An opaque, single-use token for an email-change confirmation link."""
    return secrets.token_urlsafe(32)


#: Directory-profile fields whose visibility a member sets individually
#: (Public / Members only / Private) via the editor. Identity fields (name,
#: role, committees) are always public and aren't listed here. ``email`` and
#: ``phone`` govern ``public_email`` / ``public_phone``.
TOGGLEABLE_PUBLIC_FIELDS = (
    "pronouns",
    "bio",
    "credentials",
    "languages_spoken",
    "location",
    "year_joined",
    "website",
    "specialties",
    "email",
    "phone",
)


def default_field_visibility() -> dict[str, str]:
    """New profiles start with every field Public (the school lists members by
    default) except ``phone``, which defaults to members-only since a phone
    number is more sensitive. Members adjust any field from the editor. Uses
    literal values to avoid referencing Profile here."""
    return {
        key: ("members" if key == "phone" else "public")
        for key in TOGGLEABLE_PUBLIC_FIELDS
    }


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

    class Modality(models.TextChoices):
        IN_PERSON = "in_person", _("In person")
        PHONE = "phone", _("By phone")
        VIDEO = "video", _("By online video")

    class Visibility(models.TextChoices):
        PUBLIC = "public", _("Public")
        MEMBERS = "members", _("Members only")
        PRIVATE = "private", _("Private (staff only)")

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
    timezone = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text=(
            "User's preferred timezone (IANA name, e.g. 'America/New_York'). "
            "Empty = use project default (Pacific Time)."
        ),
    )
    is_faculty = models.BooleanField(
        default=False,
        help_text="Faculty axis (USR-6). Orthogonal to role.",
    )
    # LSP Staff and Cartel Coordinator are now unified onto ``core.StaffRole``
    # (keys ``lsp_staff`` / ``cartel_coordinator``); manage holders there or
    # check via ``core.access.has_staff_role``. ``is_faculty`` stays a Profile
    # axis.
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
        help_text=(
            "The rendered square shown across the site (circle- and "
            "square-framed). Derived from ``headshot_original`` via the "
            "self-service cropper — set it through the cropper, not by hand."
        ),
    )
    headshot_original = models.ImageField(
        upload_to="headshots/originals/%Y/",
        blank=True,
        null=True,
        help_text=(
            "The full, uncropped upload. Retained so a member can reopen the "
            "cropper and re-center / re-zoom without re-uploading."
        ),
    )
    headshot_crop = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Cropper state {x, y, width, height, rotate, scaleX, scaleY} in "
            "natural-image pixels, so the cropper reopens where the member "
            "left it. Empty dict ⇒ no crop recorded yet."
        ),
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
        help_text=(
            "Latitude of the *primary* geocoded location. For members with a "
            "single location this is the only coord; for members listing two "
            "(e.g. 'San Francisco & Palo Alto, CA') see ``location_pins`` for "
            "the full set."
        ),
    )
    location_lng = models.FloatField(
        null=True,
        blank=True,
        help_text="Longitude of the primary geocoded location.",
    )
    location_pins = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "List of {lat, lng, label} dicts for the Find-an-Analyst map. "
            "Populated by geocode_profiles by splitting ``location`` on "
            "' & ', ' and ', or '/'. Empty list ⇒ render just (location_lat, "
            "location_lng) as a single pin."
        ),
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
        help_text=(
            "Private/on-file number for staff; never shown publicly. The "
            "publicly listed number is ``public_phone``. E.164; parsed as US "
            "if no country code."
        ),
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
    public_phone = PhoneNumberField(
        blank=True,
        help_text=(
            "Public-facing phone shown on the directory. Distinct from "
            "``phone`` (kept on file for staff and never shown publicly) so a "
            "member can list an office line while keeping a personal number "
            "private. Unlike email, this does NOT fall back to ``phone``."
        ),
    )
    display_name = models.CharField(
        max_length=150,
        blank=True,
        help_text=(
            "Preferred name to show instead of first+last (e.g. a member who "
            "goes by a name other than their legal first name). Falls back to "
            "the User's first+last when blank (see Profile.display_full_name)."
        ),
    )
    pronouns = models.CharField(
        max_length=40,
        blank=True,
        help_text="e.g. 'she/her', 'he/him', 'they/them'. Shown on the directory.",
    )
    website = models.URLField(
        blank=True,
        help_text="Personal or professional website, linked from the directory.",
    )
    specialties = models.TextField(
        blank=True,
        help_text=(
            "Areas of interest / clinical specialties / theoretical focus. "
            "Shown on the directory; feeds Find-an-Analyst context."
        ),
    )
    consultation_modalities = models.CharField(
        max_length=64,
        blank=True,
        help_text=(
            "Comma-separated subset of Modality values (in_person, phone, "
            "video) describing how this member meets analysands. Drives the "
            "Find-an-Analyst modality filter."
        ),
    )
    year_joined = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Start year of the academic year this member joined the school "
            "(e.g. 2018 ⇒ 'AY 2018–2019'). Self-reported; we're harvesting it."
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
        default=True,
        help_text=(
            "Master switch: whether this member is listed in the public member "
            "directory and the Find-an-Analyst map at all. Defaults to listed "
            "(the school lists members by default); members may opt out for "
            "privacy. Does not affect event pages they teach."
        ),
    )
    field_visibility = models.JSONField(
        default=default_field_visibility,
        blank=True,
        help_text=(
            "Per-field visibility map {field_key: 'public'|'members'|'private'} "
            "for TOGGLEABLE_PUBLIC_FIELDS. 'members' shows only to "
            "authenticated users; 'private' only to staff (and the member). "
            "Applied wherever the field is rendered — see Profile.visible_to()."
        ),
    )
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.user.email} ({self.get_role_display()})"

    @property
    def display_email(self) -> str:
        """Email to show on public pages; falls back to the login email."""
        return self.public_email or self.user.email

    def visibility_of(self, field_key: str) -> str:
        """This member's chosen visibility level for ``field_key`` (defaults to
        Public). See TOGGLEABLE_PUBLIC_FIELDS / Profile.Visibility."""
        return (self.field_visibility or {}).get(field_key, self.Visibility.PUBLIC)

    def visible_to(self, field_key: str, user) -> bool:
        """Whether ``field_key`` should be shown to ``user`` (an auth user or
        AnonymousUser/None). Public → everyone; Members only → any
        authenticated user; Private → staff or the member themselves."""
        level = self.visibility_of(field_key)
        if level == self.Visibility.PUBLIC:
            return True
        if user is not None and getattr(user, "is_authenticated", False):
            if user.is_staff or user.pk == self.user_id:
                return True
            if level == self.Visibility.MEMBERS:
                return True
        return False

    def visible_fields(self, user) -> dict[str, bool]:
        """Map of {field_key: visible?} for ``user`` across all toggleable
        fields — convenient for templates (which can't call methods w/ args)."""
        return {k: self.visible_to(k, user) for k in TOGGLEABLE_PUBLIC_FIELDS}

    @property
    def display_phone(self):
        """Public phone to show on the directory — ``public_phone`` only; the
        private ``phone`` is never exposed (no fallback, unlike email)."""
        return self.public_phone

    @property
    def display_full_name(self) -> str:
        """Preferred display name; falls back to the User's first+last."""
        return (
            self.display_name.strip()
            or f"{self.user.first_name} {self.user.last_name}".strip()
            or self.user.email
        )

    @property
    def modalities_list(self) -> list[str]:
        """Parsed consultation_modalities tokens (order-preserving)."""
        return [m for m in self.consultation_modalities.split(",") if m]

    @property
    def modalities_display(self) -> list[str]:
        """Human labels for the member's consultation modalities."""
        labels = dict(self.Modality.choices)
        return [str(labels[m]) for m in self.modalities_list if m in labels]

    @property
    def academic_year_joined(self) -> str:
        """``year_joined`` rendered as 'AY 2018–2019', or '' when unset."""
        if not self.year_joined:
            return ""
        return f"AY {self.year_joined}–{self.year_joined + 1}"

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

    #: Roles that owe tuition each academic year (M7.5 — see tuition_lifecycle).
    IN_TRAINING_ROLES = frozenset({
        "pre_candidate",
        "candidate",
        "pre_candidate_scholar",
        "candidate_scholar",
    })

    @property
    def is_in_directory(self) -> bool:
        """Whether this profile's *role* is eligible for /directory/."""
        return self.role in self.DIRECTORY_ROLES

    @property
    def is_listed(self) -> bool:
        """Whether this profile is actually shown publicly — role-eligible
        *and* not opted out (drives the directory query and nav links)."""
        return self.is_in_directory and self.public

    @property
    def owes_tuition(self) -> bool:
        """Whether this profile's role obligates them to pay tuition each year."""
        return self.role in self.IN_TRAINING_ROLES

    def current_tuition_enrollment(self, on_date=None):
        """The TuitionEnrollment row for the period covering ``on_date``, or None.

        Returns None when there's no TuitionPeriod for the date, or no
        enrollment row recorded for this user in that period (i.e.
        "no decision yet").
        """
        from payments.models import TuitionEnrollment, TuitionPeriod
        period = TuitionPeriod.current(on_date)
        if period is None:
            return None
        return TuitionEnrollment.objects.filter(
            user=self.user, tuition_period=period,
        ).first()

    def is_tuition_current(self, on_date=None) -> bool:
        """Source of truth for "is this user tuition-paying this year?".

        Returns True when the user has a current-period enrollment with a
        ``covers_seminars`` status (committed / payment_plan / paid_in_full).
        Returns False for SKIPPING, no row, or no current period.
        """
        enr = self.current_tuition_enrollment(on_date)
        return bool(enr and enr.covers_seminars)

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


class EmailChangeRequest(models.Model):
    """A pending change to a user's *login* email (``User.email``).

    Verify-before-switch: the new address must prove control by clicking a
    link before the login email actually changes. The token is opaque and
    single-use; requests expire after :attr:`TOKEN_TTL`. Creating a new
    request supersedes any prior unconfirmed one for the same user.
    """

    TOKEN_TTL = timedelta(hours=24)

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="email_change_requests",
    )
    new_email = models.EmailField()
    token = models.CharField(
        max_length=64, unique=True, default=_email_change_token, editable=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        state = "confirmed" if self.confirmed_at else "pending"
        return f"{self.user.email} → {self.new_email} ({state})"

    def is_expired(self, now=None) -> bool:
        return (now or timezone.now()) - self.created_at > self.TOKEN_TTL

    @property
    def is_pending(self) -> bool:
        return self.confirmed_at is None and not self.is_expired()
