"""Events, sessions, pricing tiers, and faculty-issued pricing codes.

Implements the core data model for Milestone 2:

- ``Event`` — a seminar or special event (PROG-1, PROG-4).
- ``Session`` — an individual meeting within an event; per-class billing
  (REG-6) and the unified calendar (PROG-6) hang off this.
- ``PriceTier`` — the conditional-pricing rules (REG-3, REG-4, REG-5, REG-6).
- ``PricingCode`` — faculty escape hatch for alternate pricing (REG-17).
"""

from __future__ import annotations

import datetime as _dt
import secrets
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from core.storage import private_storage

from .ce import CECreditBasis, credits_label

# Excludes visually ambiguous characters (0/O, 1/I/L).
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

#: Academic-year boundary. Months >= this start a *new* academic year, i.e.
#: a course starting Sept 2025 is academic year "2025-2026".
ACADEMIC_YEAR_START_MONTH = 9

#: Ceiling on a pricing code's installment count (task #501). A sanity bound,
#: not a policy — twelve monthly payments already outlasts any event we run.
MAX_INSTALLMENTS = 12


def _speaker_invitation_token() -> str:
    """Opaque, single-use token for an external-speaker invitation link."""
    return secrets.token_urlsafe(32)


def academic_year_of(d: _dt.date) -> str:
    """Return the academic-year label that a given date falls within.

    >>> academic_year_of(date(2025, 9, 1))  # Sept 2025
    '2025-2026'
    >>> academic_year_of(date(2026, 6, 30))  # June 2026
    '2025-2026'
    """
    if d.month >= ACADEMIC_YEAR_START_MONTH:
        return f"{d.year}-{d.year + 1}"
    return f"{d.year - 1}-{d.year}"


def academic_year_date_range(label: str) -> tuple[_dt.date, _dt.date]:
    """Return [start, end) bounds for an academic-year label like "2025-2026"."""
    start_year_str, _sep, end_year_str = label.partition("-")
    start_year = int(start_year_str)
    end_year = int(end_year_str)
    return (
        _dt.date(start_year, ACADEMIC_YEAR_START_MONTH, 1),
        _dt.date(end_year, ACADEMIC_YEAR_START_MONTH, 1),
    )


def current_academic_year(today: _dt.date | None = None) -> str:
    return academic_year_of(today or _dt.date.today())


class Program(models.Model):
    """The Lacanian School's annual program for an academic year.

    Owns the set of seminar / reading-group / cartel events for that year.
    Public visibility of those events cascades from ``Program.is_public_now``:
    a program is public when its ``published`` flag is True, OR when its
    ``publish_date`` is set and in the past (the timer auto-publishes it).

    Special events, Days of Assembly, Working Days, and Scholarly Seminars
    are *not* program-owned — they keep individual ``Event.published``.
    """

    academic_year = models.CharField(
        max_length=20, unique=True,
        help_text="e.g. '2026-2027'.",
    )
    name = models.CharField(
        max_length=100, blank=True,
        help_text="Optional display name; defaults to 'Program {academic_year}'.",
    )
    description = models.TextField(
        blank=True,
        help_text="Optional intro shown on /program/?year=... when published.",
    )
    published = models.BooleanField(
        default=False,
        help_text=(
            "If True, the program and its events are publicly visible on "
            "/program/ and /events/. If False, only Program Committee members "
            "and staff can preview."
        ),
    )
    publish_date = models.DateTimeField(
        null=True, blank=True,
        help_text=(
            "If set and in the past, the program is treated as published — "
            "use this to schedule a program release for a future moment."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-academic_year",)

    def __str__(self):
        return self.name or f"Program {self.academic_year}"

    @property
    def is_public_now(self) -> bool:
        """True when the program should be publicly visible right now."""
        if self.published:
            return True
        if self.publish_date is not None:
            from django.utils import timezone
            return self.publish_date <= timezone.now()
        return False

    @classmethod
    def for_year(cls, academic_year: str):
        return cls.objects.filter(academic_year=academic_year).first()

    @classmethod
    def public_program_year_q(cls):
        """Q expression for ``Event``-side filters: program is public now."""
        from django.db.models import Q
        from django.utils import timezone
        return Q(program__published=True) | Q(program__publish_date__lte=timezone.now())


def generate_pricing_code() -> str:
    """Generate a short, human-friendly pricing code."""
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))


class Speaker(models.Model):
    """A presenter on an event — typically external to LSP, no User account.

    Use this for guest speakers, visiting faculty from other institutions,
    or anyone who shouldn't have an LSP login. For LSP-affiliated faculty
    who teach a seminar, add them as faculty (``Event.set_faculty`` — a
    FACULTY role on the event's workgroup) instead so they can edit the event
    and see the roster.
    """

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    bio = models.TextField(blank=True)
    affiliation = models.CharField(
        max_length=200,
        blank=True,
        help_text="e.g. 'Dublin City University'.",
    )
    headshot = models.ImageField(upload_to="speakers/%Y/", blank=True, null=True)
    email = models.EmailField(
        blank=True,
        help_text="Contact email — not a login. Optional, staff-visible.",
    )
    public = models.BooleanField(
        default=True,
        help_text="Whether to show this speaker on public event pages.",
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="external_speaker",
        help_text=(
            "Optional login for this external presenter (task #463). Linking a "
            "user lets them join the meeting and see the event's presenter view, "
            "scoped to events they present. Leave blank for display-only speakers."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        if self.affiliation:
            return f"{self.name} ({self.affiliation})"
        return self.name


class CEOrganization(models.Model):
    """A body that accredits events for continuing-education credits.

    A shared library rather than a per-event upload: the same accreditor
    approves many events, and its logos and mandated approval language should be
    correctable in one place. Faculty add an entry inline when theirs is not
    listed yet, so nobody curates the collection, it accretes from use.
    """

    name = models.CharField(max_length=120)
    url = models.URLField(
        blank=True,
        help_text="The organization's site. Links the logos when set.",
    )
    statement = models.TextField(
        blank=True,
        help_text="Approval language this body requires on approved events. "
        "Shown under its logos on every event that claims it.",
    )
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ce_organizations_added",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(Lower("name"), name="ce_organization_name_ci_unique"),
        ]

    def __str__(self) -> str:
        return self.name

    def add_logos(self, blobs):
        """Append normalized WebP blobs as logo rows, after the current last.

        ``blobs`` are the ContentFiles ``ce_images.normalize_logo`` returns, so
        both editing surfaces store identical, already-bounded images.
        """
        from django.utils.text import slugify

        start = (self.logos.aggregate(models.Max("sort_order"))["sort_order__max"] or 0) + 1
        stem = slugify(self.name) or "ce-organization"
        created = []
        for offset, blob in enumerate(blobs):
            order = start + offset
            logo = CEOrganizationLogo(organization=self, sort_order=order)
            logo.image.save(f"{stem}-{order}.webp", blob, save=False)
            logo.save()
            created.append(logo)
        return created


class CEOrganizationLogo(models.Model):
    """One mark belonging to a CE accreditor.

    A body can require more than one image on an approved event's page, e.g. a
    sponsor logo alongside an approved-provider seal, so the logo is a set on
    the organization rather than a single field. Every event claiming the
    organization shows the whole set.
    """

    organization = models.ForeignKey(
        "events.CEOrganization", on_delete=models.CASCADE, related_name="logos",
    )
    image = models.ImageField(upload_to="ce-organizations/")
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("sort_order", "pk")

    def __str__(self) -> str:
        return f"{self.organization.name} logo {self.sort_order}"


class SpeakerInvitation(models.Model):
    """A pending invitation for an external speaker to activate a login.

    Own token (not Django's password reset, which silently skips
    unusable-password accounts — memory ``auth-email-scanner-and-reset-gotchas``).
    Opaque + single-use; a generous expiry (default 30 days) so an invitation
    sent well before the event still works. Refreshing supersedes the prior link.
    """

    DEFAULT_TTL = _dt.timedelta(days=30)

    speaker = models.ForeignKey(
        "events.Speaker", on_delete=models.CASCADE, related_name="invitations"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="speaker_invitations",
    )
    token = models.CharField(
        max_length=64, unique=True, default=_speaker_invitation_token, editable=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        state = "used" if self.used_at else ("expired" if self.is_expired() else "pending")
        return f"invite {self.speaker.name} ({state})"

    def is_expired(self, now=None) -> bool:
        from django.utils import timezone

        return (now or timezone.now()) > self.expires_at

    @property
    def is_valid(self) -> bool:
        return self.used_at is None and not self.is_expired()

    def consume(self) -> None:
        from django.utils import timezone

        if self.used_at is None:
            self.used_at = timezone.now()
            self.save(update_fields=["used_at"])

    def refresh(self, expires_at=None) -> None:
        from django.utils import timezone

        self.token = _speaker_invitation_token()
        self.used_at = None
        self.expires_at = expires_at or (timezone.now() + self.DEFAULT_TTL)
        self.save(update_fields=["token", "used_at", "expires_at"])


class Event(models.Model):
    class Type(models.TextChoices):
        # --- Annual-program types (live on /program/) ---
        SEMINAR = "seminar", _("Seminar")
        READING_GROUP = "reading_group", _("Reading group")
        CARTEL = "cartel", _("Cartel")
        # --- Standalone / one-off events (live on /events/) ---
        SPECIAL_EVENT = "special_event", _("Special event")
        DAY_OF_ASSEMBLY = "day_of_assembly", _("Day of Assembly")
        WORKING_DAY = "working_day", _("Working Day")
        SCHOLARLY_SEMINAR = "scholarly_seminar", _("Scholarly Seminar Series")

    class Visibility(models.TextChoices):
        PUBLIC = "public", _("Public")
        MEMBERS_ONLY = "members_only", _("Members only")

    #: Types that belong on /program/ rather than /events/.
    ANNUAL_PROGRAM_TYPES = frozenset({"seminar", "reading_group", "cartel"})

    class Format(models.TextChoices):
        ONLINE = "online", _("Online")
        IN_PERSON = "in_person", _("In person")
        HYBRID = "hybrid", _("Hybrid")

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        OPEN = "open", _("Open for registration")
        CLOSED = "closed", _("Closed")

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    description = models.TextField(
        blank=True,
        help_text="Editable by faculty for events they teach (PROG-7).",
    )
    readings = models.TextField(
        blank=True,
        help_text=(
            "Reading list, one citation per line (notes and sub-headings may "
            "be lines too). Rendered as a formatted list on the event page."
        ),
    )
    schedule_note = models.TextField(
        blank=True,
        help_text=(
            "Human-readable meeting cadence ('1st and 3rd Saturdays, 9–11:30am "
            "Pacific'). Shown alongside the sessions table — keeps the faculty's "
            "own phrasing even once sessions are generated."
        ),
    )
    contact = models.CharField(
        max_length=200,
        blank=True,
        help_text="Public contact for questions about the event (email/phone).",
    )
    fee_note = models.TextField(
        blank=True,
        help_text=(
            "Fee in the faculty's own words ('$100 donation encouraged, none "
            "turned away'). Shown with the pricing table — the table drives "
            "checkout; this preserves the human phrasing."
        ),
    )
    event_type = models.CharField(
        max_length=20,
        choices=Type.choices,
        default=Type.SEMINAR,
    )
    # Faculty (LSP-affiliated instructors) are no longer a field on Event:
    # they live on the generated seminar Workgroup as
    # ``WorkgroupMembership(role=FACULTY)`` — the single source of truth for the
    # roster. Read/write via ``faculty_members()`` / ``set_faculty()`` /
    # ``is_faculty()`` below.
    speakers = models.ManyToManyField(
        "events.Speaker",
        related_name="events",
        blank=True,
        help_text=(
            "External presenters with no LSP account. For LSP-affiliated "
            "presenters with a User account, use ``member_speakers`` instead "
            "so we don't duplicate their bio/headshot. For instructors who "
            "should be able to edit the event, add them as faculty (a role on "
            "the event's workgroup)."
        ),
    )
    member_speakers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="events.EventMemberSpeaker",
        related_name="speaking_engagements",
        blank=True,
        help_text=(
            "LSP-affiliated presenters (User accounts). Bio defaults to "
            "Profile.bio but can be overridden per-event via the "
            "EventMemberSpeaker through model. Display-only — does not grant "
            "edit access."
        ),
    )
    workgroup = models.ForeignKey(
        "workgroups.Workgroup",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="events",
        help_text=(
            "The workgroup that generates/owns this event (Workgroup-primary "
            "model — see docs/design-workgroup-events.md). For offerings it's "
            "the offering's own group; for special events it's the organizing "
            "committee. A group may generate many events over time."
        ),
    )
    start_date = models.DateField()
    end_date = models.DateField()
    format = models.CharField(
        max_length=20,
        choices=Format.choices,
        default=Format.ONLINE,
    )
    access_info = models.TextField(
        blank=True,
        help_text="Venue/room, dial-in, or an external meeting link. Released to "
        "registrants only after payment (REG-8). Leave blank if using the in-site "
        "meeting room — registrants get a Join button automatically.",
    )
    record_video = models.BooleanField(
        default=False,
        help_text="Automatically record this event's online meeting (a host's "
        "browser starts the recording on join). Off by default; recordings are "
        "stored privately and shown per their visibility setting.",
    )
    speaker_spotlight = models.BooleanField(
        default=False,
        help_text="Speaker spotlight (task #463): attendees join the online "
        "meeting with mic and camera off, so the speaker is the focus. It's a "
        "soft spotlight, attendees can still turn them back on, and hosts can "
        "mute. Off by default; suited to a talk or lecture.",
    )

    class RecordingMode(models.TextChoices):
        ON_DEMAND = "on_demand", "On demand — hosts can record"
        OFF = "off", "Off — no Record button"

    recording_mode = models.CharField(
        max_length=12,
        choices=RecordingMode.choices,
        default=RecordingMode.ON_DEMAND,
        help_text="Whether hosts see a Record button in this event's own meeting "
        "room. Only applies to one-off events (special events, Days of Assembly, "
        "Working Days, Scholarly Seminars), which get their own room.",
    )
    registration_opens = models.DateTimeField(null=True, blank=True)
    registration_closes = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    published = models.BooleanField(
        default=False,
        help_text="Whether the public event page is visible (PROG-1).",
    )
    requires_faculty_approval = models.BooleanField(
        default=False,
        help_text=(
            "If set, each registration must be approved by the event's faculty "
            "before it's confirmed (future proposal-flow option). Default off; "
            "all existing seminars are off."
        ),
    )
    visibility = models.CharField(
        max_length=20,
        choices=Visibility.choices,
        default=Visibility.PUBLIC,
        help_text=(
            "Members-only events (e.g. Scholarly Seminar Series) are hidden "
            "from anonymous visitors on public listings."
        ),
    )
    open_to_guests = models.BooleanField(
        default=True,
        help_text=(
            "Non-members are welcome to register for this event. Shows a "
            "guests-welcome note on the event page. This is messaging only; "
            "it does not restrict who can register."
        ),
    )

    # ---- Continuing education (task #486) ----
    #: Master switch. Ticked once an accrediting body has approved the event;
    #: drives whether the CE panel renders at all.
    offers_ce = models.BooleanField(
        default=False, verbose_name="Approved for CE credits",
    )
    ce_credits = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Leave blank if the body has not set a count yet.",
    )
    ce_credits_basis = models.CharField(
        max_length=12, choices=CECreditBasis.choices, default=CECreditBasis.TOTAL,
    )
    ce_note = models.TextField(
        blank=True,
        help_text="Anything specific to this event, e.g. full attendance "
        "required for credit.",
    )
    ce_organizations = models.ManyToManyField(
        "events.CEOrganization", blank=True, related_name="events",
        verbose_name="Approved by",
    )

    program = models.ForeignKey(
        "events.Program",
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="events",
        help_text=(
            "Set for annual-program-type events (seminar, reading group, "
            "cartel) — links the event to its academic-year Program. Drives "
            "public visibility via Program.is_public_now."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-start_date", "title")

    def __str__(self):
        return self.title

    def clean(self):
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "end_date must be on or after start_date."})

    @property
    def academic_year(self) -> str:
        """Academic-year label this event belongs to ("2025-2026")."""
        return academic_year_of(self.start_date)

    @property
    def registration_badge(self) -> dict:
        """A small status badge for listings: ``{"label", "css"}`` (DaisyUI
        badge class). Past events read as Archived; otherwise the registration
        status drives it."""
        import datetime as _dt

        if not self.published:
            return {"label": "Draft", "css": "badge-warning"}
        if self.end_date and self.end_date < _dt.date.today():
            return {"label": "Archived", "css": "badge-ghost"}
        if self.status == self.Status.OPEN:
            return {"label": "Registration open", "css": "badge-success"}
        if self.status == self.Status.CLOSED:
            return {"label": "Registration closed", "css": "badge-ghost"}
        return {"label": "Opening soon", "css": "badge-outline"}

    def readings_entries(self) -> list[str]:
        """The reading list as individual entries (one per non-blank line),
        for formatted rendering on the event page."""
        return [ln.strip() for ln in self.readings.splitlines() if ln.strip()]

    @property
    def ce_credits_label(self) -> str:
        """The public CE sentence, or "" when this event offers no credits."""
        return credits_label(self.offers_ce, self.ce_credits, self.ce_credits_basis)

    @property
    def is_offering(self) -> bool:
        """True for reading groups / cartels — the "Other Offerings" bucket."""
        return self.event_type in {self.Type.READING_GROUP, self.Type.CARTEL}

    #: Event types whose approved instances route content edits through review.
    REVIEW_LOOP_TYPES = (Type.SEMINAR, Type.READING_GROUP, Type.SPECIAL_EVENT)

    def requires_change_review(self) -> bool:
        """Whether faculty edits to this event's content should offer the
        certify-or-submit dialog (task #295).

        Scope: published events of a proposable type that were minted from an
        approved Programming-Committee proposal. Drafts and staff-created
        events (no originating proposal) edit freely as before.
        """
        if not self.published or self.event_type not in self.REVIEW_LOOP_TYPES:
            return False
        return self.from_proposal.filter(
            status=EventProposal.Status.APPROVED
        ).exists()

    @property
    def is_public_now(self) -> bool:
        """Whether this event is publicly visible right now.

        Annual-program-type events (seminars, reading groups, cartels) cascade
        from ``Program.is_public_now``: when the program is published or its
        scheduled publish_date is in the past, the event is public. Other
        event types use the standalone ``published`` flag.

        Fallback: if an annual-program-type event has no Program attached
        (e.g. historical data being migrated, or test fixtures), the event's
        own ``published`` flag is used. Production data is backfilled by
        migration ``events.0012_program_backfill``; new events created from
        the PC admin will always have a Program.
        """
        if self.event_type in self.ANNUAL_PROGRAM_TYPES:
            if self.program is not None:
                return self.program.is_public_now
            return self.published
        return self.published

    # ---- Workgroup attachment (Stage 5) ----

    # ---- Faculty (stored as a role on the generated workgroup) ----

    def _faculty_memberships(self):
        """Active FACULTY memberships on this event's workgroup (empty if the
        event has no workgroup yet)."""
        from workgroups.models import WorkgroupMembership

        if not self.workgroup_id:
            return WorkgroupMembership.objects.none()
        return WorkgroupMembership.objects.serving().filter(
            workgroup_id=self.workgroup_id,
            role=WorkgroupMembership.Role.FACULTY,
        ).select_related("user")

    def faculty_members(self):
        """The event's faculty (LSP instructors), read from the workgroup
        roster. List of User objects — usable directly in templates."""
        return [m.user for m in self._faculty_memberships()]

    def is_faculty(self, user) -> bool:
        if not getattr(user, "is_authenticated", False):
            return False
        return self._faculty_memberships().filter(user=user).exists()

    def is_presenter(self, user) -> bool:
        """True if ``user`` presents at this *PC-organized* event as a listed
        member speaker (task #463).

        A PC-organized event (special event, assembly, work day, scholarly)
        shares the Programming Committee's workgroup, so its faculty can't be
        stored as a role there: that would put the presenter on the PC roster
        and make them faculty of every PC event. Their presenters are recorded
        as ``member_speakers`` (LSP members) or, for external presenters, as an
        ``events.Speaker`` with a linked login (task #463) — either earns the
        event's faculty surfaces, scoped to the one event.

        Offerings (seminar / reading group / cartel) have their own workgroup
        where real faculty live, so a member/external speaker there is a guest
        and gets nothing.
        """
        if not getattr(user, "is_authenticated", False):
            return False
        if self.event_type in self.ANNUAL_PROGRAM_TYPES:
            return False
        if self.member_speakers.filter(pk=user.pk).exists():
            return True
        # External presenters with a linked login (task #463) are presenters of
        # this one event too — same per-event grant, via the Speaker.user link.
        return self.speakers.filter(user=user).exists()

    def add_faculty(self, user):
        """Idempotent: give ``user`` the FACULTY role on this event's workgroup.

        Teaching a seminar confers faculty standing: the first time a user is
        made faculty of a SEMINAR, set ``Profile.is_faculty``.
        """
        from django.utils import timezone

        from workgroups.models import WorkgroupMembership

        wg = self.ensure_workgroup()
        if wg is None:
            return None
        existing = wg.memberships.serving().filter(user=user).first()
        if existing:
            if existing.role != WorkgroupMembership.Role.FACULTY:
                existing.role = WorkgroupMembership.Role.FACULTY
                existing.save(update_fields=["role"])
            membership = existing
        else:
            membership = WorkgroupMembership.objects.create(
                workgroup=wg, user=user, role=WorkgroupMembership.Role.FACULTY,
                start_date=timezone.now().date(),
            )
        if self.event_type == self.Type.SEMINAR:
            profile = getattr(user, "profile", None)
            if profile is not None and not profile.is_faculty:
                profile.is_faculty = True
                profile.save(update_fields=["is_faculty"])
        return membership

    def set_faculty(self, users):
        """Reconcile the faculty roster to exactly ``users``: add missing
        FACULTY memberships, end-date faculty no longer in the set. Members
        with a *non-faculty* role on the workgroup are left untouched."""
        from django.utils import timezone

        wg = self.ensure_workgroup()
        if wg is None:
            return
        target = {u.pk: u for u in users}
        current = {m.user_id: m for m in self._faculty_memberships()}
        for uid, m in current.items():
            if uid not in target:
                m.end_date = timezone.localdate()
                m.save(update_fields=["end_date"])
        for uid, user in target.items():
            if uid not in current:
                self.add_faculty(user)

    # ---- Workspace roster (faculty + registrants) ----

    def has_access_registrant(self, user) -> bool:
        """True if ``user`` has a paid/comped Registration for this event — the
        *derived* portion of the workspace roster (kept out of the workgroup's
        stored memberships; see ``Workgroup.is_member``).

        A treasurer-suspended member (``Profile.seminar_access_suspended``,
        task #450 phase D) never counts here — the ONLY way this flag is set
        is a manual, audited treasurer action (do-not-over-automate); this
        check is what makes that flip actually cut access. Faculty are stored
        memberships, not registrants, so they are unaffected."""
        if not getattr(user, "is_authenticated", False):
            return False
        if getattr(getattr(user, "profile", None), "seminar_access_suspended", False):
            return False
        from registrations.models import Registration

        return self.registrations.filter(
            user=user,
            status__in=(Registration.Status.PAID, Registration.Status.COMPED),
        ).exists()

    def access_registrant_users(self):
        """Users with a paid/comped Registration — the derived participants for
        ``Workgroup.participants()``. Excludes treasurer-suspended members
        (see ``has_access_registrant``)."""
        from registrations.models import Registration

        return [
            r.user for r in self.registrations.filter(
                status__in=(Registration.Status.PAID, Registration.Status.COMPED),
            ).select_related("user", "user__profile")
            if r.user_id
            and not getattr(getattr(r.user, "profile", None),
                             "seminar_access_suspended", False)
        ]

    def is_workgroup_member(self, user) -> bool:
        """Roster for this event's attached workspace: faculty + registrants
        who have access (paid or comped)."""
        return self.is_faculty(user) or self.has_access_registrant(user)

    # ---- Live timing (drives the video-room "Join" gating) ----

    #: How early the room opens before a session, and how long after it ends the
    #: join stays available — a buffer around the "live" window.
    JOIN_PREOPEN = _dt.timedelta(minutes=15)
    JOIN_GRACE = _dt.timedelta(minutes=30)

    def live_session(self, now=None):
        """The session whose window (± the pre-open/grace buffers) contains ``now``,
        else None. Used to surface the online-event Join button only when live."""
        from django.utils import timezone

        now = now or timezone.now()
        for s in self.sessions.order_by("start_at"):
            if s.start_at - self.JOIN_PREOPEN <= now <= s.end_at + self.JOIN_GRACE:
                return s
        return None

    def is_live(self, now=None) -> bool:
        """True while the event is joinable. Session-based when sessions exist;
        otherwise the event's whole date span counts as live."""
        from django.utils import timezone

        if self.live_session(now) is not None:
            return True
        if not self.sessions.exists() and self.start_date and self.end_date:
            today = (now or timezone.now()).date()
            return self.start_date <= today <= self.end_date
        return False

    def next_session(self, now=None):
        """The soonest session that hasn't started yet (for 'opens at …' copy)."""
        from django.utils import timezone

        now = now or timezone.now()
        return self.sessions.filter(start_at__gte=now).order_by("start_at").first()

    def resequence_sessions(self):
        """Renumber this event's sessions so ``sequence`` matches chronological
        order (1-based by ``start_at``). The page already displays sessions by
        date, so the stored number is purely a label — keep it in sync with the
        date order it's read as. Uses ``bulk_update`` (no save signals fired),
        so it's safe to call from the Session post_save/post_delete signals.
        Returns the list of rows whose number changed."""
        sessions = list(self.sessions.order_by("start_at", "id"))
        changed = []
        for i, s in enumerate(sessions, start=1):
            if s.sequence != i:
                s.sequence = i
                changed.append(s)
        if changed:
            Session.objects.bulk_update(changed, ["sequence"])
        return changed

    #: Event types organized by the Programming Committee (not their own group).
    PC_OWNED_TYPES = frozenset({
        "special_event", "day_of_assembly", "working_day", "scholarly_seminar",
    })

    def ensure_workgroup(self):
        """Ensure this event has a generating workgroup, and return it.

        Workgroup-primary model (docs/design-workgroup-events.md): an annual-
        program offering (seminar / reading group / cartel) gets its own
        offering Workgroup of the matching kind (which auto-provisions a channel
        via the Parlêtre signal); a PC-organized event (special / assembly /
        work day / scholarly) links to the Programming Committee's workgroup.
        Idempotent. Returns None only if a PC-owned event can't find the PC
        workgroup.
        """
        if self.workgroup_id is not None:
            return self.workgroup
        from workgroups.models import Workgroup, build_workgroup

        offering_kind = {
            self.Type.SEMINAR: Workgroup.Kind.SEMINAR,
            self.Type.READING_GROUP: Workgroup.Kind.READING_GROUP,
            self.Type.CARTEL: Workgroup.Kind.CARTEL,
        }.get(self.event_type)

        if offering_kind is not None:
            slug, n = self.slug[:140], 2
            while Workgroup.objects.filter(slug=slug).exists():
                slug = f"{self.slug[:135]}-{n}"
                n += 1
            self.workgroup = build_workgroup(
                offering_kind,
                name=self.title[:120],   # Workgroup.name is max_length=120
                slug=slug,
                description=self.description or "",
                landing_visibility="members",
                content_visibility="private",
            )
        else:
            # PC-organized event → the Programming Committee's workgroup.
            from committees.models import Committee

            pc = Committee.objects.filter(slug="programming-committee").first()
            if pc is None or pc.workgroup_id is None:
                return None
            self.workgroup_id = pc.workgroup_id

        self.save(update_fields=["workgroup"])
        return self.workgroup

    # ---- Feature image (task #504) ----

    def feature(self):
        """This event's feature image row, or ``None``.

        ``getattr`` with a default is safe on a reverse one-to-one: Django's
        ``RelatedObjectDoesNotExist`` subclasses ``AttributeError`` precisely so
        this works.
        """
        return getattr(self, "feature_image", None)


class EventFeatureImage(models.Model):
    """The image an event leads with (task #504).

    A separate row rather than nine more fields on ``Event``: absence of the row
    *is* "no image", removal is a delete, and the rights record stays beside the
    file it licenses. The shape is settled at upload (see
    ``events.feature_images``) so every render site meets a shape it can lay out.
    """

    class Source(models.TextChoices):
        PUBLIC_DOMAIN = "public_domain", "Public domain"
        LICENSED = "licensed", "Licensed"
        OWN_WORK = "own_work", "My own work"
        PERMISSION = "permission", "Permission granted by the rights holder"

    event = models.OneToOneField(
        Event, on_delete=models.CASCADE, related_name="feature_image",
    )
    image = models.ImageField(
        upload_to="events/feature/%Y/",
        width_field="image_width", height_field="image_height",
        help_text="Rendered WebP, derived from the upload via feature_images.render().",
    )
    # Denormalized: media lives in S3 in production, so reading image.width at
    # render time is a network round trip per page view. Storing them also lets
    # the <img> reserve its space before the file arrives.
    image_width = models.PositiveIntegerField(default=0)
    image_height = models.PositiveIntegerField(default=0)
    image_full = models.ImageField(
        upload_to="events/feature/full/%Y/", blank=True,
        width_field="image_full_width", height_field="image_full_height",
        help_text=(
            "Larger render for the full-size view. Blank when the upload was "
            "too small for this to differ from `image`."
        ),
    )
    image_full_width = models.PositiveIntegerField(default=0)
    image_full_height = models.PositiveIntegerField(default=0)
    original = models.ImageField(
        upload_to="events/feature/originals/%Y/", blank=True,
        help_text="The bounded upload, kept so the framing can be revised later.",
    )
    crop = models.JSONField(
        blank=True, null=True,
        help_text=(
            "Cropper.js rect in natural-image pixels, so the framing modal "
            "reopens where it was left."
        ),
    )
    credit = models.CharField(
        max_length=200, blank=True,
        help_text='Shown small under the image, e.g. "René Magritte, The Treachery of Images".',
    )
    alt = models.CharField(
        max_length=300, blank=True,
        help_text="Description for screen readers. Blank falls back to the event title.",
    )
    source = models.CharField(max_length=20, choices=Source.choices)
    source_url = models.URLField(
        blank=True, help_text="Required when the source is Licensed.",
    )
    rights_confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    rights_confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Feature image for {self.event}"

    @property
    def alt_text(self) -> str:
        """What the ``alt`` attribute should say. Never blank."""
        return self.alt or self.event.title

    @property
    def modal_image(self):
        """The file the full-size view serves.

        ``image_full`` is absent whenever the upload was too small for it to
        differ from the page render, so this saves every template from having
        to know that.
        """
        return self.image_full or self.image


class EventMemberSpeaker(models.Model):
    """Through model for ``Event.member_speakers``.

    Lets an LSP member appear as a speaker on a specific event. Bio +
    headshot + credentials come from the user's Profile (with
    ``Profile.event_bio`` as the alternate-when-speaking fallback path).
    """

    event = models.ForeignKey("events.Event", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    sort_order = models.PositiveIntegerField(
        default=0,
        help_text="Lower numbers appear first. Ties break on name.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["event", "user"],
                name="event_member_speaker_unique",
            ),
        ]
        ordering = ["sort_order", "user__last_name", "user__first_name"]

    def __str__(self):
        return f"{self.user.first_name} {self.user.last_name} @ {self.event.slug}"


class Session(models.Model):
    """A single meeting within an event — calendar's unit of display.

    Sessions are typically generated in bulk by the recurrence helper
    (PROG-5) and then independently editable so a single date can move
    without re-running the pattern.
    """

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="sessions")
    title = models.CharField(max_length=200, blank=True)
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    location = models.CharField(
        max_length=200,
        blank=True,
        help_text="Room name or address for in-person/hybrid sessions.",
    )
    sequence = models.PositiveIntegerField(
        default=0,
        help_text="Stable ordering within an event.",
    )

    class Meta:
        ordering = ("event", "sequence", "start_at")
        indexes = [models.Index(fields=["start_at"])]

    def __str__(self):
        label = self.title or f"Session {self.sequence}"
        return f"{self.event.title} — {label} ({self.start_at.date().isoformat()})"

    def clean(self):
        if self.end_at and self.start_at and self.end_at <= self.start_at:
            raise ValidationError({"end_at": "end_at must be after start_at."})


class Audience(models.TextChoices):
    """Pricing audience — Profile.Role values plus ``all``."""

    ALL = "all", _("All")
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


class PriceTier(models.Model):
    """A price for an event (or a single session) keyed to an audience."""

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="price_tiers")
    session = models.ForeignKey(
        Session,
        on_delete=models.CASCADE,
        related_name="price_tiers",
        null=True,
        blank=True,
        help_text="Set only for per-class pricing (REG-6).",
    )
    audience = models.CharField(
        max_length=32,
        choices=Audience.choices,
        default=Audience.ALL,
    )
    base_amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        help_text="Listed price in USD.",
    )
    sliding_scale = models.BooleanField(
        default=False,
        help_text="If true, the payer may choose any amount at or above minimum_amount (REG-5).",
    )
    minimum_amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Floor for sliding-scale tiers; 0 expresses 'none turned away'.",
    )
    covered_by_tuition = models.BooleanField(
        default=False,
        help_text=(
            "If set, tuition-current members in this tier's audience get this "
            "event for free (REG-4). Whether a given event is tuition-covered "
            "is decided here, per-event: a special event with no "
            "covered_by_tuition tier charges tuition-paying members the "
            "standard tier amount."
        ),
    )

    class Meta:
        ordering = ("event", "session", "audience")

    def __str__(self):
        scope = f"session {self.session_id}" if self.session_id else "event"
        return f"{self.event.title} / {self.get_audience_display()} ({scope}): ${self.base_amount}"

    def clean(self):
        if self.sliding_scale and self.minimum_amount is None:
            raise ValidationError(
                {"minimum_amount": "minimum_amount is required when sliding_scale is true."}
            )
        if (
            self.minimum_amount is not None
            and self.minimum_amount > self.base_amount
        ):
            raise ValidationError(
                {"minimum_amount": "minimum_amount cannot exceed base_amount."}
            )


class PricingCode(models.Model):
    """A faculty-issued alternate-pricing token for an event (REG-17)."""

    class Mode(models.TextChoices):
        PERCENT_OFF = "percent_off", _("Percent off")
        FIXED_AMOUNT = "fixed_amount", _("Fixed amount")
        SLIDING_FLOOR = "sliding_floor", _("Sliding-scale floor")
        #: No discount at all — the code exists only to carry a payment plan
        #: (task #501). ``amount_or_percent`` is unused and stored as 0.
        FULL_PRICE = "full_price", _("Full price — payment plan only")

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="pricing_codes")
    code = models.CharField(max_length=20, unique=True, db_index=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="pricing_codes_issued",
        help_text="Faculty member who minted the code.",
    )
    pricing_mode = models.CharField(max_length=20, choices=Mode.choices)
    amount_or_percent = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        help_text=(
            "Interpreted per pricing_mode: percent_off → 0–100 (percent), "
            "fixed_amount → USD price, sliding_floor → USD minimum the "
            "participant must meet or exceed."
        ),
    )
    valid_until = models.DateTimeField(null=True, blank=True)
    max_uses = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Null = unlimited.",
    )
    uses_remaining = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Decremented on successful redemption. Null when max_uses is null.",
    )
    installments = models.PositiveSmallIntegerField(
        default=1,
        help_text=(
            "1 = pay in full at registration. A higher number splits the fee "
            "into that many payments, the first due at registration and the "
            "rest spread across the event's run. The total never changes."
        ),
    )
    restricted_to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pricing_codes_eligible",
        help_text="When set, only that user can redeem.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.code} ({self.event.title})"

    def save(self, *args, **kwargs):
        if not self.code:
            # Retry on the unlikely collision; the alphabet/length give ~10^11 combos.
            for _attempt in range(5):
                candidate = generate_pricing_code()
                if not PricingCode.objects.filter(code=candidate).exists():
                    self.code = candidate
                    break
            else:
                raise RuntimeError("Could not generate a unique pricing code after 5 attempts.")
        if self.uses_remaining is None and self.max_uses is not None:
            self.uses_remaining = self.max_uses
        super().save(*args, **kwargs)

    def clean(self):
        # Bound the schedule first — the amount checks below return early on a
        # blank amount, which would skip this.
        if self.installments is not None and not (
            1 <= self.installments <= MAX_INSTALLMENTS
        ):
            raise ValidationError({
                "installments": f"Choose between 1 and {MAX_INSTALLMENTS} payments.",
            })
        # Form-level clean strips invalid fields from the instance; guard against None.
        if self.amount_or_percent is None:
            return
        if self.pricing_mode == self.Mode.PERCENT_OFF and not (
            Decimal("0") <= self.amount_or_percent <= Decimal("100")
        ):
            raise ValidationError(
                {"amount_or_percent": "percent_off requires a value between 0 and 100."}
            )
        if self.amount_or_percent < 0:
            raise ValidationError({"amount_or_percent": "Cannot be negative."})

    def is_redeemable(self, *, user=None, now=None) -> bool:
        """True if this code can currently be redeemed (optionally by ``user``)."""
        from django.utils import timezone

        now = now or timezone.now()
        if self.valid_until and now > self.valid_until:
            return False
        if self.max_uses is not None and (self.uses_remaining or 0) <= 0:
            return False
        if (
            self.restricted_to_user_id
            and user is not None
            and user.pk != self.restricted_to_user_id
        ):
            return False
        # (issued_by's faculty standing is enforced at mint time via
        # can_edit_event → Event.is_faculty, not re-checked on redemption.)
        return True


class EventProposal(models.Model):
    """A faculty member's proposal to run a seminar (M12.5).

    The Programming Committee reviews it; on approval it mints a SEMINAR
    ``Event`` — a brand-new standing seminar, or a new yearly term of an
    existing one via ``continues_seminar`` — attached to the target academic
    year's ``Program``. Direct PC event creation (``program_admin_event_new``)
    remains the other path (dual-path, G1).

    A standalone typed record rather than a ``workgroups.WorkgroupProposal``:
    that model is one-per-workgroup, which a *continuing* seminar (whose
    workgroup already exists and carries its own proposal) can't satisfy, and a
    pre-approval proposal has no workgroup yet.
    """

    class Status(models.TextChoices):
        SAVED = "saved", _("Saved — not yet submitted")
        PROPOSED = "proposed", _("Proposed — under review")
        APPROVED = "approved", _("Approved")
        DECLINED = "declined", _("Declined")

    #: Event types a member may propose (others — Days of Assembly, Working Days,
    #: the Scholarly Seminar Series — stay PC/Board-curated in admin).
    PROPOSABLE_TYPES = (
        Event.Type.SEMINAR,
        Event.Type.READING_GROUP,
        Event.Type.SPECIAL_EVENT,
    )

    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="seminar_proposals",
    )
    event_type = models.CharField(
        max_length=20,
        choices=[
            (Event.Type.SEMINAR, "Seminar"),
            (Event.Type.READING_GROUP, "Reading group"),
            (Event.Type.SPECIAL_EVENT, "Special event"),
        ],
        default=Event.Type.SEMINAR,
        help_text="What kind of event you're proposing.",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    # Nullable so a special event can be proposed with its date still TBD.
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    class LocationKind(models.TextChoices):
        ONLINE_INSITE = "online_insite", "Online — in-site video room"
        IN_PERSON = "in_person", "In person"
        HYBRID = "hybrid", "Hybrid (in person + online)"

    location_kind = models.CharField(
        max_length=20, choices=LocationKind.choices, default=LocationKind.ONLINE_INSITE,
        help_text="Where it meets.",
    )
    location = models.CharField(
        max_length=300, blank=True,
        help_text="Venue address (in person or hybrid). Leave blank when online.",
    )
    contact = models.CharField(
        max_length=200, blank=True, help_text="Contact email for this proposal.",
    )
    continues_seminar = models.ForeignKey(
        "workgroups.Workgroup", on_delete=models.SET_NULL, null=True, blank=True,
        limit_choices_to={"kind": "seminar"}, related_name="seminar_proposals",
        help_text="Optional: propose a new yearly term of this existing seminar.",
    )
    faculty = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="proposed_seminars",
    )

    # ---- Fee (offerings + special events) ----
    fee_amount = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text="Flat fee in USD. Leave blank for free / sliding-scale.",
    )
    fee_sliding_min = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text="Sliding-scale floor (0 = none turned away).",
    )
    fee_sliding_max = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text="Sliding-scale ceiling / suggested amount.",
    )
    tuition_covers = models.BooleanField(
        default=True,
        help_text="Tuition-current members attend at no charge. Always on for "
        "seminars and reading groups.",
    )

    # ---- Seminar / reading-group proposal-guide fields ----
    offers_ce = models.BooleanField(
        default=False,
        help_text="Offer APA CE credits (you apply to GPPA separately).",
    )
    #: The count the proposer *expects* to offer. Accreditation happens after
    #: the proposal (faculty apply to GPPA separately), so this is an estimate;
    #: the real figure is confirmed on the event edit form once approval lands.
    ce_credits = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="If you know it yet. You can set or change this later.",
    )
    ce_credits_basis = models.CharField(
        max_length=12, choices=CECreditBasis.choices, default=CECreditBasis.TOTAL,
    )

    # ---- Seminar / reading-group meeting schedule (optional; materializes into a
    # MeetingSeries on the workgroup at approval). Date range comes from the term
    # (start_date/end_date). ----
    schedule_tbd = models.BooleanField(
        default=True, help_text="Schedule the recurring meetings now, or leave TBD.",
    )

    class ScheduleFrequency(models.TextChoices):
        WEEKLY = "weekly", "Weekly"
        BIWEEKLY = "biweekly", "Every 2 weeks"
        MONTHLY = "monthly", "Monthly (nth weekday)"

    sched_frequency = models.CharField(
        max_length=12, choices=ScheduleFrequency.choices, blank=True,
    )
    sched_weekdays = models.CharField(max_length=32, blank=True)  # MO,TU,…
    #: Weekday-occurrence ordinals for monthly, comma-coded ("1,3" = 1st & 3rd).
    sched_week_positions = models.CharField(max_length=20, blank=True)
    sched_start_time = models.TimeField(null=True, blank=True)
    sched_end_time = models.TimeField(null=True, blank=True)

    # ---- Special-event fields ----
    date_tbd = models.BooleanField(
        default=False, help_text="Check if the date/time is TBD (not yet decided).",
    )
    proposed_datetime = models.DateTimeField(
        null=True, blank=True, help_text="Proposed date & time (Pacific).",
    )

    class SpeakerArrangement(models.TextChoices):
        PROPOSER = "proposer", "I'll arrange with the speaker(s) directly"
        PC = "pc", "I'd like the Program Committee to arrange it"

    speaker_arrangement = models.CharField(
        max_length=12, choices=SpeakerArrangement.choices, blank=True,
        default=SpeakerArrangement.PROPOSER,
        help_text="Who contacts/arranges with the speakers.",
    )
    honoraria_estimate = models.CharField(
        max_length=120, blank=True,
        help_text="Estimated speaker honoraria, if any.",
    )

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PROPOSED,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="seminar_proposals_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True, help_text="Decline reason / review notes.")
    minted_event = models.ForeignKey(
        "events.Event", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="from_proposal",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.title} ({self.get_status_display()})"

    @property
    def academic_year(self) -> str:
        return academic_year_of(self.start_date) if self.start_date else ""

    @property
    def ce_credits_label(self) -> str:
        return credits_label(self.offers_ce, self.ce_credits, self.ce_credits_basis)

    def missing_for_submission(self) -> str:
        """Human list of what's still needed before a saved proposal can be
        submitted for review (empty string when ready)."""
        missing = []
        if self.event_type in Event.ANNUAL_PROGRAM_TYPES:
            if not self.start_date or not self.end_date:
                missing.append("start and end dates")
        elif not self.date_tbd and not self.proposed_datetime:
            missing.append("a date/time (or mark it TBD)")
        return ", ".join(missing)

    @property
    def event_format(self):
        """The Event.Format derived from the proposed location kind."""
        return {
            self.LocationKind.IN_PERSON: Event.Format.IN_PERSON,
            self.LocationKind.HYBRID: Event.Format.HYBRID,
        }.get(self.location_kind, Event.Format.ONLINE)

    def _build_price_tier(self, event):
        """Create a PriceTier on the minted event from the proposed fee."""
        sliding = self.fee_sliding_min is not None or self.fee_sliding_max is not None
        if not sliding and self.fee_amount is None and not self.tuition_covers:
            return  # nothing specified
        base = self.fee_amount
        if base is None:
            base = self.fee_sliding_max if self.fee_sliding_max is not None else Decimal("0")
        PriceTier.objects.create(
            event=event, audience=Audience.ALL, base_amount=base,
            sliding_scale=sliding,
            minimum_amount=(self.fee_sliding_min or Decimal("0")) if sliding else Decimal("0"),
            covered_by_tuition=self.tuition_covers,
        )

    def _build_meeting_series(self, event, reviewer):
        """Materialize the proposed recurring schedule into a MeetingSeries on the
        event's workgroup (+ generate occurrences). Term range = the proposal's
        start/end dates."""
        wg = event.workgroup
        if wg is None or not (self.start_date and self.end_date):
            return
        from workgroups.models import MeetingSeries
        series = MeetingSeries.objects.create(
            workgroup=wg, title=self.title[:255], frequency=self.sched_frequency,
            weekdays=self.sched_weekdays or "MO",
            week_positions=self.sched_week_positions or "1",
            start_date=self.start_date, end_date=self.end_date,
            start_time=self.sched_start_time, end_time=self.sched_end_time,
            location=self.location, created_by=reviewer,  # the event's own venue
        )
        series.generate()

    def _attach_speakers(self, event):
        """Mint external Speaker rows from the proposal and attach them."""
        from django.utils.text import slugify
        for ps in self.proposal_speakers.all():
            base = slugify(ps.name) or "speaker"
            slug, n = base, 2
            while Speaker.objects.filter(slug=slug).exists():
                slug, n = f"{base[:46]}-{n}", n + 1
            speaker = Speaker.objects.create(
                name=ps.name[:200], slug=slug[:200], bio=ps.bio,
                affiliation=ps.affiliation[:200], email=ps.email,
            )
            event.speakers.add(speaker)

    def _unique_event_slug(self) -> str:
        from django.utils.text import slugify

        base = (slugify(self.title) or "seminar")[:200]
        slug, n = base, 2
        while Event.objects.filter(slug=slug).exists():
            slug = f"{base[:194]}-{n}"
            n += 1
        return slug

    @transaction.atomic
    def approve(self, reviewer):
        """Mint the proposed Event and wire it up per its type.
        Idempotent: returns the already-minted event if not PROPOSED.

        - Seminar → OPEN; standing SEMINAR workgroup + faculty (confers faculty
          standing); ``continues_seminar`` adds a new term to an existing one.
        - Reading group → OPEN; own READING_GROUP workgroup; conveners added as
          ORGANIZERs (reading groups are organizer-led, not faculty).
        - Special event → DRAFT (the PC finalizes pricing/access before
          publishing); links to the PC workgroup for *provenance only* — nobody
          is added to the PC roster, so proposers/presenters never leak into the
          committee.
        """
        if self.status != self.Status.PROPOSED:
            return self.minted_event
        from django.utils import timezone

        is_offering = self.event_type in Event.ANNUAL_PROGRAM_TYPES
        program = None
        if is_offering:
            program, _ = Program.objects.get_or_create(academic_year=self.academic_year)
        # A special event's concrete date comes from proposed_datetime; a TBD one
        # mints with a placeholder date (Event requires one) and stays unpublished.
        has_real_date = (
            bool(self.start_date) if is_offering
            else (bool(self.proposed_datetime) and not self.date_tbd)
        )
        if is_offering:
            start_date, end_date = self.start_date, self.end_date
        elif self.proposed_datetime:
            start_date = end_date = timezone.localtime(self.proposed_datetime).date()
        else:
            start_date = end_date = timezone.localdate()  # TBD placeholder
        # In-person / hybrid venue details flow into access_info.
        access_info = self.location if self.location_kind != self.LocationKind.ONLINE_INSITE else ""
        # Approved = a real event (never a "draft"). A special event with a
        # concrete date is published immediately; a TBD one stays unpublished
        # until the PC sets its date.
        event = Event.objects.create(
            title=self.title[:200], slug=self._unique_event_slug(),
            event_type=self.event_type,
            start_date=start_date, end_date=end_date,
            format=self.event_format, access_info=access_info,
            status=Event.Status.OPEN,
            published=(not is_offering and has_real_date),
            description=self.description, program=program,
            readings="\n".join(r.citation for r in self.readings.all()),
            contact=self.contact,
            offers_ce=self.offers_ce,
            ce_credits=self.ce_credits,
            ce_credits_basis=self.ce_credits_basis,
        )
        self._build_price_tier(event)
        # A concrete special-event date/time becomes the event's first Session.
        if not is_offering and self.proposed_datetime:
            from datetime import timedelta
            Session.objects.create(
                event=event, start_at=self.proposed_datetime,
                end_at=self.proposed_datetime + timedelta(hours=2), sequence=1,
                location=self.location,
            )
        if self.event_type == Event.Type.SEMINAR:
            # Continuing seminar → attach its existing standing workgroup so
            # ensure_workgroup() adds a new term rather than spawning a fresh one.
            if self.continues_seminar_id and event.workgroup_id is None:
                event.workgroup_id = self.continues_seminar_id
                event.save(update_fields=["workgroup"])
            # set_faculty() calls ensure_workgroup(), creating the standing
            # SEMINAR workgroup (+ its channel) for a brand-new seminar.
            event.set_faculty(list(self.faculty.all()))
        elif self.event_type == Event.Type.READING_GROUP:
            from workgroups.models import WorkgroupMembership

            wg = event.ensure_workgroup()
            conveners = list(self.faculty.all())
            if not conveners and self.proposed_by_id:
                conveners = [self.proposed_by]
            for u in conveners:
                WorkgroupMembership.objects.get_or_create(
                    workgroup=wg, user=u,
                    defaults={
                        "role": WorkgroupMembership.Role.ORGANIZER,
                        "start_date": timezone.localdate(),
                    },
                )
        else:
            # Special event: provenance link to the PC workgroup only — no roster
            # changes (avoids leaking proposers/presenters into the committee).
            event.ensure_workgroup()
            # Internal LSP speakers → display-only member_speakers (NOT faculty,
            # which would add them to the PC workgroup roster). External speakers
            # → Speaker rows. The PC owns/edits the event.
            for u in self.faculty.all():
                event.member_speakers.add(u)
            self._attach_speakers(event)
        # Offerings with a scheduled cadence get a real MeetingSeries on their
        # workgroup (members manage individual occurrences there afterward).
        if is_offering and not self.schedule_tbd and self.sched_frequency:
            self._build_meeting_series(event, reviewer)
        self.status = self.Status.APPROVED
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.minted_event = event
        self.save(update_fields=["status", "reviewed_by", "reviewed_at", "minted_event"])
        return event

    def decline(self, reviewer, note=""):
        from django.utils import timezone

        self.status = self.Status.DECLINED
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.review_note = note
        self.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note"])

    def resubmit(self):
        """A declined proposal, edited, re-enters review."""
        if self.status != self.Status.DECLINED:
            return
        self.status = self.Status.PROPOSED
        self.reviewed_by = None
        self.reviewed_at = None
        self.review_note = ""
        self.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note"])


class ProposalReading(models.Model):
    """A single reading on a EventProposal, stored individually so the list can
    be formatted (one MLA-style citation per row, ordered)."""

    proposal = models.ForeignKey(
        EventProposal, on_delete=models.CASCADE, related_name="readings",
    )
    sort_order = models.PositiveIntegerField(default=0)
    citation = models.TextField()

    class Meta:
        ordering = ("sort_order", "id")

    def __str__(self) -> str:
        return self.citation[:80]


class ProposalSpeaker(models.Model):
    """An external (non-LSP) speaker proposed for a special event — minted into a
    Speaker row on approval. Internal speakers use the member picker instead."""

    proposal = models.ForeignKey(
        EventProposal, on_delete=models.CASCADE, related_name="proposal_speakers",
    )
    sort_order = models.PositiveIntegerField(default=0)
    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    affiliation = models.CharField(max_length=200, blank=True)
    bio = models.TextField(blank=True)

    class Meta:
        ordering = ("sort_order", "id")

    def __str__(self) -> str:
        return self.name


class ArchivedProgram(models.Model):
    """A past academic-year program preserved as a downloadable PDF.

    The new ``Program``/``Event`` model only goes back so far; earlier years
    live on as the original program PDFs, surfaced from the /program/ Archive.
    Files are kept in private storage and served only through the gated
    download view (members-only for now)."""

    academic_year = models.CharField(
        max_length=20,
        unique=True,
        help_text="e.g. '2008-2009' or '1994'.",
    )
    label = models.CharField(
        max_length=120,
        blank=True,
        help_text="Optional display label; defaults to the academic year.",
    )
    file = models.FileField(upload_to="program-archive/", storage=private_storage)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-academic_year",)

    def __str__(self) -> str:
        return self.label or f"Program {self.academic_year}"

    @property
    def display_label(self) -> str:
        return self.label or self.academic_year


class EventChangeRequest(models.Model):
    """A faculty edit to an approved event's reviewable content (task #295).

    Every content edit that passes through the certify-or-submit dialog leaves
    one of these as an audit record. Three terminal states are reached without
    the committee (the change is applied immediately): a faculty member
    self-certifying a minor change, and a PC/staff reviewer adopting a change
    either as minor or explicitly as an administrative override. The fourth path
    holds the proposed values for committee review and applies them only on
    approval — the live event is untouched until then.
    """

    class Status(models.TextChoices):
        # Applied immediately on submit:
        SELF_CERTIFIED = "self_certified", _("Self-certified minor")
        ADMINISTRATIVE = "administrative", _("Administrative change")
        # Routed to the Programming Committee:
        PENDING = "pending", _("Pending committee review")
        APPROVED = "approved", _("Approved")
        DECLINED = "declined", _("Declined")
        WITHDRAWN = "withdrawn", _("Withdrawn")

    #: Statuses whose proposed values are (or will be) live on the event.
    APPLIED_STATUSES = (Status.SELF_CERTIFIED, Status.ADMINISTRATIVE, Status.APPROVED)

    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="change_requests",
    )
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="event_change_requests",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING,
    )

    #: Which reviewable fields this request changes (subset of REVIEWABLE_FIELDS).
    changed_fields = models.JSONField(default=list)
    #: Advisory description-change fraction at submission time (0.0–1.0).
    description_change_ratio = models.FloatField(default=0.0)

    # Proposed (new) values for the reviewable fields.
    proposed_title = models.CharField(max_length=200, blank=True)
    proposed_description = models.TextField(blank=True)
    proposed_readings = models.TextField(blank=True)
    proposed_fee_note = models.TextField(blank=True)

    # Snapshot of the live values when the request was created (for the diff).
    original_title = models.CharField(max_length=200, blank=True)
    original_description = models.TextField(blank=True)
    original_readings = models.TextField(blank=True)
    original_fee_note = models.TextField(blank=True)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="event_changes_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"Change to {self.event.title} ({self.get_status_display()})"

    @property
    def is_applied(self) -> bool:
        return self.status in self.APPLIED_STATUSES

    def field_changes(self):
        """List of ``(label, old, new)`` tuples for the changed fields, for the
        review queue + dialog diff display."""
        from .review import FIELD_LABELS
        out = []
        for f in self.changed_fields:
            out.append((
                FIELD_LABELS.get(f, f),
                getattr(self, f"original_{f}"),
                getattr(self, f"proposed_{f}"),
            ))
        return out

    def apply(self):
        """Copy the proposed values onto the live event."""
        from django.utils import timezone
        for f in self.changed_fields:
            setattr(self.event, f, getattr(self, f"proposed_{f}"))
        if self.changed_fields:
            self.event.save(update_fields=list(self.changed_fields))
        self.applied_at = timezone.now()

    def approve(self, reviewer):
        """PC approves a pending change — apply it to the event."""
        from django.utils import timezone
        if self.status != self.Status.PENDING:
            return
        self.apply()
        self.status = self.Status.APPROVED
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.save()

    def decline(self, reviewer, note: str = ""):
        """PC declines a pending change — the live event is left untouched."""
        from django.utils import timezone
        if self.status != self.Status.PENDING:
            return
        self.status = self.Status.DECLINED
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.review_note = note
        self.save()
