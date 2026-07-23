import secrets
from datetime import timedelta

from django.contrib.auth.models import AbstractUser
from django.db import models, transaction
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from phonenumber_field.modelfields import PhoneNumberField

from .managers import UserManager


def _email_change_token() -> str:
    """An opaque, single-use token for an email-change confirmation link."""
    return secrets.token_urlsafe(32)


def _magic_login_token() -> str:
    """An opaque, single-use token for a passwordless sign-in link."""
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
        EXTERNAL = "external", _("Auditor")

    class Standing(models.TextChoices):
        """Membership standing — orthogonal to role. Active is the default; the
        Board records transitions (on-leave, resigned, emeritus, retired,
        removed) via Membership administration. Deceased is a separate axis
        (``deceased_on``), not a standing."""
        ACTIVE = "active", _("Active")
        ON_LEAVE = "on_leave", _("On leave")
        RESIGNED = "resigned", _("Resigned")
        EMERITUS = "emeritus", _("Emeritus")
        RETIRED = "retired", _("Retired")
        REMOVED = "removed", _("Removed")

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
    standing = models.CharField(
        max_length=16,
        choices=Standing.choices,
        default=Standing.ACTIVE,
        help_text="Membership standing (active / on leave / resigned / emeritus / "
        "retired / removed). Live cache; the Board sets it via Membership "
        "administration.",
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
    seminar_access_suspended = models.BooleanField(
        default=False,
        help_text="Treasurer-set: excluded from seminar group rosters until "
        "the outstanding balance is settled.",
    )
    clinical_background = models.BooleanField(
        default=False,
        help_text="Clinical background requires two control analyses "
                  "(one of at least 4 years, one of at least 2 years); "
                  "academic requires three (one of at least 4 years, two of "
                  "at least 2 years). Set at acceptance from the application; "
                  "adjustable by an advisor or admin.",
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
    deceased_on = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "Date recorded as deceased. Orthogonal to standing — a member may "
            "be Retired and Deceased. Setting this disables the account "
            "(login off) for security; the member stays listed in the "
            "directory with an 'In memoriam' marker."
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
    #: Opaque token for the member's private iCal feed (generated on first use).
    calendar_token = models.CharField(max_length=64, blank=True, default="", db_index=True)
    is_persona = models.BooleanField(
        default=False,
        help_text=(
            "A disposable test persona (not a real member). The Web Coordinator "
            "may impersonate personas with full write access; impersonating a "
            "real member is read-only. Seeded by `manage.py seed_personas`."
        ),
    )
    persona_owner = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="owned_personas",
        help_text=(
            "For a training-sandbox persona: the trainee who owns it. Mail "
            "addressed to this persona is redirected to the owner (tagged "
            "[SANDBOX]) instead of dropped, so they see the whole workflow. "
            "Set by `manage.py seed_sandbox`."
        ),
    )

    def __str__(self):
        return f"{self.user.email} ({self.get_role_display()})"

    def add_note(self, text: str, *, save=True) -> None:
        """Append a dated line to the audit trail (mirrors
        ``payments.models.Charge.add_note`` — same convention, so treasurer
        actions read the same wherever they land)."""
        from django.utils import timezone

        line = f"[{timezone.now().date()}] {text}"
        self.notes = (self.notes + "\n" + line) if self.notes else line
        if save:
            self.save(update_fields=("notes",))

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

    #: Standings that are NOT members: no members-only access, off the public
    #: directory, not counted in member dashboards. Resigned joins Removed here.
    NON_MEMBER_STANDINGS = frozenset({"resigned", "removed"})

    #: Standings dropped from the Find-an-Analyst referral distribution pool
    #: (they are no longer taking new analysands). Deceased is excluded too, via
    #: ``is_deceased``. Emeritus / on-leave keep their referral listing.
    REFERRAL_EXCLUDED_STANDINGS = frozenset({"retired", "resigned", "removed"})

    #: Roles that owe tuition each academic year (M7.5 — see tuition_lifecycle).
    IN_TRAINING_ROLES = frozenset({
        "pre_candidate",
        "candidate",
        "pre_candidate_scholar",
        "candidate_scholar",
    })

    #: Formation tracks — used to determine who may advise whom.
    ANALYST_TRACK_ROLES = frozenset({"pre_candidate", "candidate", "analyst"})
    SCHOLAR_TRACK_ROLES = frozenset({
        "pre_candidate_scholar", "candidate_scholar", "scholar",
    })

    @property
    def needs_advisor(self) -> bool:
        """In-training members (Precandidates / Candidates) choose an Advisor."""
        return self.role in self.IN_TRAINING_ROLES

    @property
    def is_in_directory(self) -> bool:
        """Whether this profile's *role* is eligible for /directory/."""
        return self.role in self.DIRECTORY_ROLES

    @property
    def is_listed(self) -> bool:
        """Shown publicly: role-eligible, opted in, and not a non-member
        standing. Deceased members stay listed (with a memorial marker)."""
        return (
            self.is_in_directory
            and self.public
            and self.standing not in self.NON_MEMBER_STANDINGS
        )

    @property
    def is_deceased(self) -> bool:
        return self.deceased_on is not None

    @property
    def is_active_member(self) -> bool:
        """Whether this profile currently counts as a member for access +
        dashboards: a directory role, an active-enough standing, and not
        deceased. (Directory *listing* keeps deceased — see the directory qs.)"""
        return (
            self.role in self.DIRECTORY_ROLES
            and self.standing not in self.NON_MEMBER_STANDINGS
            and not self.is_deceased
        )

    @property
    def owes_tuition(self) -> bool:
        """Whether this profile owes tuition each year — an in-training role held
        with active standing. On-leave / resigned / emeritus students are exempt
        (and so aren't blocked by the registration tuition gate)."""
        if self.is_persona:
            return False  # personas are test accounts — never financially obligated
        if self.standing != self.Standing.ACTIVE:
            return False  # on leave / resigned / emeritus → not obligated
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

    def control_requirement(self) -> dict:
        """How many control analyses this member owes, by slot. Clinical
        background: one 4-year + one 2-year. Academic: one 4-year + two 2-year."""
        return {"four_year": 1, "two_year": 1 if self.clinical_background else 2}

    @property
    def directory_slug(self) -> str:
        """URL slug for this profile's /directory/<slug>/ page."""
        return (
            slugify(f"{self.user.first_name} {self.user.last_name}".strip())
            or str(self.user.pk)
        )

    # Geocode-staling snapshot fields (see save()); ``_UNSET`` means the
    # instance wasn't loaded from the DB, so we read the old value on demand.
    _GEOCODE_UNSET = object()

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        for f in ("location", "location_lat", "location_lng", "deceased_on"):
            if f in field_names:
                setattr(instance, "_loaded_" + f, values[field_names.index(f)])
        return instance

    def _stale_geocode_snapshot(self):
        """Return the ``(location, lat, lng)`` last read from the DB, falling
        back to a query when this instance wasn't loaded from the DB (or had
        those columns deferred)."""
        loc = getattr(self, "_loaded_location", self._GEOCODE_UNSET)
        lat = getattr(self, "_loaded_location_lat", self._GEOCODE_UNSET)
        lng = getattr(self, "_loaded_location_lng", self._GEOCODE_UNSET)
        if self._GEOCODE_UNSET in (loc, lat, lng):
            if self.pk is None:
                return None
            row = (
                type(self).objects.filter(pk=self.pk)
                .values("location", "location_lat", "location_lng").first()
            )
            if row is None:
                return None
            return row["location"], row["location_lat"], row["location_lng"]
        return loc, lat, lng

    def save(self, *args, **kwargs):
        if not self.is_faculty:
            self.default_billing_mode = None

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_fields = set(update_fields)

        # Invalidate a stale geocode whenever ``location`` changes — at the
        # model level so *every* save path (admin, imports, scripts) behaves
        # like the self-service editor, not just it (task #391). Skip when the
        # caller is also writing new coords in the same save (e.g. the
        # geocode_profiles command, or object setup), so we don't clobber them.
        # ``_geocode_stale`` signals interactive edit surfaces to re-geocode.
        self._geocode_stale = False
        location_being_saved = update_fields is None or "location" in update_fields
        snapshot = self._stale_geocode_snapshot() if location_being_saved else None
        if snapshot is not None:
            old_location, old_lat, old_lng = snapshot
            location_changed = old_location != self.location
            coords_untouched = (
                self.location_lat == old_lat and self.location_lng == old_lng
            )
            if location_changed and coords_untouched:
                self.location_lat = None
                self.location_lng = None
                self.location_pins = []
                self._geocode_stale = True
                if update_fields is not None:
                    update_fields |= {
                        "location_lat", "location_lng", "location_pins"
                    }
                    kwargs["update_fields"] = update_fields

        # Deceased ⇒ account disabled (security); cleared ⇒ re-enabled. Synced
        # at the model level so every save path (admin, lifecycle helper,
        # scripts) is consistent. Heavier side-effects (waive, referral) live in
        # accounts.lifecycle, not here. NOTE: this sync fires only through
        # Profile.save() — a bulk ``Profile.objects.update(deceased_on=...)``
        # bypasses instance save() and won't touch ``User.is_active``.
        #
        # Intent (whether a sync is needed, and the desired ``want_active``)
        # is computed here, against the pre-save snapshot, but the actual
        # ``User`` write is deferred until after ``super().save()`` succeeds
        # and wrapped with it in one atomic block — so the Profile's
        # ``deceased_on`` and the User's ``is_active`` commit together, never
        # one without the other.
        need_user_sync = False
        want_active = None
        deceased_being_saved = update_fields is None or "deceased_on" in update_fields
        if deceased_being_saved and self.user_id is not None:
            old_deceased = getattr(self, "_loaded_deceased_on", self._GEOCODE_UNSET)
            changed = old_deceased is self._GEOCODE_UNSET or old_deceased != self.deceased_on
            if changed:
                want_active = self.deceased_on is None
                if self.user.is_active != want_active:
                    need_user_sync = True

        if need_user_sync:
            with transaction.atomic():
                super().save(*args, **kwargs)
                self.user.is_active = want_active
                self.user.save(update_fields=["is_active"])
        else:
            super().save(*args, **kwargs)

        # Refresh the snapshot so a later save on the same instance compares
        # against what's now persisted.
        self._loaded_location = self.location
        self._loaded_location_lat = self.location_lat
        self._loaded_location_lng = self.location_lng
        self._loaded_deceased_on = self.deceased_on


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


class MagicLoginLink(models.Model):
    """A single-use, short-lived passwordless sign-in link.

    Mirrors :class:`EmailChangeRequest`: an opaque token emailed to the
    account's address; clicking it logs the user in. Links expire after
    :attr:`TOKEN_TTL` and are consumed on first use. Admins still hit the
    2FA challenge afterwards (see ``accounts.middleware``) when enforcement
    is on — the link only proves control of the mailbox, not the second
    factor.
    """

    TOKEN_TTL = timedelta(minutes=15)

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="magic_login_links",
    )
    token = models.CharField(
        max_length=64, unique=True, default=_magic_login_token, editable=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)
    #: Explicit expiry, overriding TOKEN_TTL when set. Used by meeting-reminder
    #: links, whose window tracks the meeting (capped — see MAX_TTL).
    expires_at = models.DateTimeField(null=True, blank=True)
    #: Reusable until expiry (vs. consumed on first click). Meeting links are
    #: multi-use so a reconnect — or an email prefetcher hitting the URL first
    #: — doesn't lock the member out during the meeting.
    multi_use = models.BooleanField(default=False)

    #: Hard cap on any explicit expiry (defense in depth for meeting links).
    MAX_TTL = timedelta(hours=9)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        state = "used" if self.used_at else ("expired" if self.is_expired() else "pending")
        return f"magic link for {self.user.email} ({state})"

    def is_expired(self, now=None) -> bool:
        now = now or timezone.now()
        if self.expires_at is not None:
            return now > self.expires_at
        return now - self.created_at > self.TOKEN_TTL

    @property
    def is_valid(self) -> bool:
        used_ok = self.multi_use or self.used_at is None
        return used_ok and not self.is_expired()

    def consume(self) -> None:
        """Record use. Single-use links can't be replayed afterwards; multi-use
        links stay valid until they expire (we still stamp the first use)."""
        if self.used_at is None:
            self.used_at = timezone.now()
            self.save(update_fields=["used_at"])

    @classmethod
    def create_for_window(cls, user, *, expires_at):
        """Mint a reusable sign-in link valid until ``expires_at`` (clamped to
        :attr:`MAX_TTL` from now). For time-boxed flows like meeting reminders."""
        cap = timezone.now() + cls.MAX_TTL
        return cls.objects.create(
            user=user, multi_use=True, expires_at=min(expires_at, cap),
        )


class TOTPDevice(models.Model):
    """A member's TOTP (authenticator-app) second factor.

    One device per user. ``confirmed`` flips True only once the member has
    proved the secret by entering a current code, so a half-finished
    enrollment never gates login. The shared secret is base32 (pyotp). Lost
    devices are recovered with one-time :class:`RecoveryCode` rows, or reset
    by deleting this row in the Django admin.
    """

    user = models.OneToOneField(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="totp_device",
    )
    secret = models.CharField(max_length=64, editable=False)
    confirmed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        state = "confirmed" if self.confirmed else "pending"
        return f"TOTP device for {self.user.email} ({state})"


class RecoveryCode(models.Model):
    """A one-time backup code for an account whose authenticator is lost.

    Codes are stored hashed (never plaintext); the plaintext set is shown to
    the member exactly once at enrollment. Verifying a code marks it used.
    """

    device = models.ForeignKey(
        "accounts.TOTPDevice",
        on_delete=models.CASCADE,
        related_name="recovery_codes",
    )
    code_hash = models.CharField(max_length=128, editable=False)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("id",)

    def __str__(self):
        state = "used" if self.used_at else "unused"
        return f"recovery code for {self.device.user.email} ({state})"


class Source(models.TextChoices):
    """Provenance of a tuition/dues/membership record.

    Lets a later authoritative import *promote* a value (e.g. self-reported →
    verified) instead of clobbering it, and lets the treasurer see how much of
    the history is confirmed vs assumed. Shared by ``MembershipTenure`` and the
    ``payments`` models (``TuitionEnrollment`` / ``Payment``)."""

    VERIFIED = "verified", _("Verified against records")
    IMPORTED = "imported", _("Imported from treasurer ledger")
    STRIPE = "stripe", _("Imported from Stripe")
    SELF_REPORTED = "self_reported", _("Member-reported (survey)")
    ASSUMED = "assumed", _("Assumed")
    STAFF = "staff", _("Entered by staff")


class MembershipTenure(models.Model):
    """One stint in one role, in academic-year terms.

    A member's tenures (ordered by ``start_ay``) reconstruct which role they
    held in any past academic year — the missing timeline that lets us derive
    per-year tuition/dues obligations instead of proxying. ``Profile.role``
    stays the live cache for present-day access/pricing; the open tenure
    (``end_ay is None``) mirrors it.
    """

    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="tenures",
    )
    role = models.CharField(max_length=32, choices=Profile.Role.choices)
    standing = models.CharField(
        max_length=16, choices=Profile.Standing.choices,
        default=Profile.Standing.ACTIVE,
    )
    start_ay = models.PositiveSmallIntegerField(
        help_text="Academic-year start year, e.g. 2019 for AY 2019–2020.",
    )
    end_ay = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="AY start year this role ended (inclusive); blank = ongoing.",
    )
    source = models.CharField(
        max_length=20, choices=Source.choices, default=Source.STAFF,
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("user", "start_ay")
        indexes = [models.Index(fields=("user", "start_ay"))]

    def __str__(self):
        end = self.end_ay if self.end_ay is not None else "present"
        return f"{self.user} — {self.get_role_display()} ({self.start_ay}–{end})"

    @property
    def ay_label(self) -> str:
        """e.g. 'AY 2019–2020' or 'AY 2019–2020 – 2021–2022'."""
        start = f"AY {self.start_ay}–{self.start_ay + 1}"
        if self.end_ay is None:
            return f"{start} – present"
        if self.end_ay == self.start_ay:
            return start
        return f"{start} – {self.end_ay}–{self.end_ay + 1}"

    @classmethod
    def open_for(cls, user):
        """The member's current open tenure (``end_ay`` null), or None."""
        return cls.objects.filter(user=user, end_ay__isnull=True).order_by("-start_ay").first()

    @classmethod
    def role_at(cls, user, ay: int):
        """The role ``user`` held in academic year ``ay`` (start year), or None."""
        tenure = (
            cls.objects.filter(user=user, start_ay__lte=ay)
            .filter(models.Q(end_ay__gte=ay) | models.Q(end_ay__isnull=True))
            .order_by("-start_ay")
            .first()
        )
        return tenure.role if tenure else None

    @classmethod
    def was_in_training(cls, user, ay: int) -> bool:
        """True if ``user`` was in an in-training (tuition-owing) role in ``ay``."""
        return cls.role_at(user, ay) in Profile.IN_TRAINING_ROLES


class Advisorship(models.Model):
    """An in-training member's Advisor — an Analyst (analyst track) or a Scholar
    or Analyst (scholar track). Precandidates and Candidates choose one as soon
    as they're admitted; it can change over time (the open row, ``end_date``
    null, is the current advisor). See the formation guidelines."""

    advisee = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="advisorships",
    )
    advisor = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="advisees",
    )
    start_date = models.DateField(default=timezone.localdate)
    end_date = models.DateField(null=True, blank=True, help_text="Null = current advisor.")
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("advisee", "-start_date")
        constraints = [
            models.UniqueConstraint(
                fields=("advisee",),
                condition=models.Q(end_date__isnull=True),
                name="accounts_one_current_advisor_per_advisee",
            ),
        ]

    def __str__(self):
        return f"{self.advisee} ← advised by {self.advisor}"


class MemberIntakeSurvey(models.Model):
    """Raw capture of a member's launch intake survey.

    Stored verbatim so we can re-derive the structured records (tenures,
    enrollments, dues payments) if our logic changes, and keep an audit trail
    separate from those records. ``grid`` holds the per-year answers, e.g.
    ``{"2024": {"tuition": true, "dues": true}}``.
    """

    user = models.OneToOneField(
        "accounts.User", on_delete=models.CASCADE, related_name="intake_survey",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    year_joined = models.PositiveSmallIntegerField(null=True, blank=True)
    payment_names = models.CharField(
        max_length=255, blank=True,
        help_text="Alternate name(s) the member used on payments.",
    )
    payment_emails = models.CharField(
        max_length=255, blank=True,
        help_text="Other email(s) used for Stripe / PayPal.",
    )
    grid = models.JSONField(default=dict, blank=True)
    milestones = models.JSONField(
        default=dict, blank=True,
        help_text='Formation-step years, e.g. {"palimpsest": 2019, "passage": 2023}.',
    )
    paid_all_tuition = models.BooleanField(
        null=True, blank=True,
        help_text="Member's belief that they've paid all four years of full "
        "tuition to date (a fallback when records are incomplete).",
    )
    applied_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When the answers were reconciled into structured records.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        state = "submitted" if self.submitted_at else "draft"
        return f"Intake survey: {self.user} ({state})"


class WelcomeEmail(models.Model):
    """One row per launch welcome email sent to a member.

    ``manage.py send_welcome_emails`` skips users with a row, so the
    one-time launch announcement can be re-run safely (new members added
    later get welcomed on the next run, nobody gets it twice).
    """

    user = models.OneToOneField(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="welcome_email",
    )
    sent_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"welcome email to {self.user.email} ({self.sent_at:%Y-%m-%d})"
