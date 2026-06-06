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
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _

# Excludes visually ambiguous characters (0/O, 1/I/L).
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

#: Academic-year boundary. Months >= this start a *new* academic year, i.e.
#: a course starting Sept 2025 is academic year "2025-2026".
ACADEMIC_YEAR_START_MONTH = 9


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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        if self.affiliation:
            return f"{self.name} ({self.affiliation})"
        return self.name


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

    @property
    def is_offering(self) -> bool:
        """True for reading groups / cartels — the "Other Offerings" bucket."""
        return self.event_type in {self.Type.READING_GROUP, self.Type.CARTEL}

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
        stored memberships; see ``Workgroup.is_member``)."""
        if not getattr(user, "is_authenticated", False):
            return False
        from registrations.models import Registration

        return self.registrations.filter(
            user=user,
            status__in=(Registration.Status.PAID, Registration.Status.COMPED),
        ).exists()

    def access_registrant_users(self):
        """Users with a paid/comped Registration — the derived participants for
        ``Workgroup.participants()``."""
        from registrations.models import Registration

        return [
            r.user for r in self.registrations.filter(
                status__in=(Registration.Status.PAID, Registration.Status.COMPED),
            ).select_related("user")
            if r.user_id
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


class SeminarProposal(models.Model):
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
    format = models.CharField(
        max_length=20, choices=Event.Format.choices, default=Event.Format.ONLINE,
    )
    location = models.CharField(
        max_length=200, blank=True,
        help_text="Proposed venue (in-person) or platform note.",
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

    # ---- Seminar / reading-group proposal-guide fields ----
    offers_ce = models.BooleanField(
        default=False,
        help_text="Offer APA CE credits (you apply to GPPA separately).",
    )
    fee_note = models.TextField(
        blank=True,
        help_text="Proposed fee, or donation language (e.g. “$100 donation "
        "encouraged, none turned away”).",
    )
    biography = models.TextField(blank=True, help_text="Instructor/convener biography.")

    # ---- Special-event fields ----
    date_tbd = models.BooleanField(
        default=False, help_text="Check if the date/time is not yet decided.",
    )
    proposed_time = models.CharField(
        max_length=120, blank=True, help_text="Proposed time (if a date is set).",
    )

    class SpeakerArrangement(models.TextChoices):
        PROPOSER = "proposer", "I'll arrange with the speaker(s) directly"
        PC = "pc", "I'd like the Programming Committee to arrange it"

    speaker_arrangement = models.CharField(
        max_length=12, choices=SpeakerArrangement.choices, blank=True,
        help_text="Who contacts/arranges with the speakers.",
    )
    external_speakers = models.TextField(
        blank=True,
        help_text="External (non-LSP) speakers: name, affiliation, contact email, "
        "and a short bio for each.",
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
        event = Event.objects.create(
            title=self.title[:200], slug=self._unique_event_slug(),
            event_type=self.event_type,
            start_date=self.start_date, end_date=self.end_date,
            format=self.format,
            status=Event.Status.OPEN if is_offering else Event.Status.DRAFT,
            description=self.description, program=program,
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
    """A single reading on a SeminarProposal, stored individually so the list can
    be formatted (one MLA-style citation per row, ordered)."""

    proposal = models.ForeignKey(
        SeminarProposal, on_delete=models.CASCADE, related_name="readings",
    )
    sort_order = models.PositiveIntegerField(default=0)
    citation = models.TextField()

    class Meta:
        ordering = ("sort_order", "id")

    def __str__(self) -> str:
        return self.citation[:80]
