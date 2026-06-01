"""The shared collaborative-group layer.

A ``Workgroup`` is the common substrate every kind of LSP group draws on: a
roster (``WorkgroupMembership``), a discussion channel, shared works + files,
and a landing page (the "Workspace" surface). Concrete group types — cartels,
working groups, committees, seminars — *attach* a Workgroup via a
``OneToOneField`` and add only their type-specific extras.

Design principle (see ``docs/design-workgroups.md``): when adding a feature
that several group types could want, put it on ``Workgroup`` — not on one of
the attaching models.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from accounts.permissions import is_lsp_member


class Visibility(models.TextChoices):
    PUBLIC = "public", _("Public — anyone")
    MEMBERS = "members", _("Members — any LSP member")
    PRIVATE = "private", _("Private — this group's members only")


#: Publicness rank for the "content can't be more public than landing"
#: invariant. Higher = more open.
_VISIBILITY_RANK = {
    Visibility.PUBLIC: 2,
    Visibility.MEMBERS: 1,
    Visibility.PRIVATE: 0,
}


@dataclass(frozen=True)
class Participant:
    """One person in a workgroup's roster, normalized for the UI.

    A workgroup's roster is the union of *stored* ``WorkgroupMembership`` rows
    (hand-managed members: faculty, cartel members, committee officers …) and,
    for offering workgroups (seminars / reading groups), *derived* participants
    whose access flows from a paid/comped Registration rather than a stored row.
    ``Workgroup.participants()`` yields these so enumeration surfaces (roster,
    assignee pickers, member counts) see everyone — while access (``is_member``)
    and the derived population stay computed from the authoritative payment
    state, never duplicated as rows. ``membership`` is ``None`` for derived
    participants (they carry no stored role or per-member state)."""

    user: object
    role: str
    is_lead: bool = False
    membership: object = None

    def get_role_display(self) -> str:
        try:
            return WorkgroupMembership.Role(self.role).label
        except ValueError:
            return self.role.replace("_", " ").title()


class Workgroup(models.Model):
    """The collaborative layer shared by every kind of LSP group."""

    class Kind(models.TextChoices):
        CARTEL = "cartel", _("Cartel")
        WORKING_GROUP = "working_group", _("Working group")
        COMMITTEE = "committee", _("Committee")
        SEMINAR = "seminar", _("Seminar")
        READING_GROUP = "reading_group", _("Reading group")

    #: Per-kind seed for the capability toggles, applied at creation (the
    #: Table A defaults from the design worksheet). Every group can still turn
    #: the full suite on afterward — these are defaults, not limits.
    KIND_TOGGLE_DEFAULTS = {
        Kind.CARTEL: {"has_calendar": True, "has_tasks": True},
        Kind.WORKING_GROUP: {
            "has_calendar": True, "has_minutes": True,
            "has_tasks": True, "has_decisions": True,
        },
        Kind.COMMITTEE: {
            "has_calendar": True, "has_minutes": True,
            "has_tasks": True, "has_decisions": True,
        },
        Kind.SEMINAR: {"has_works": False, "has_calendar": True},
        Kind.READING_GROUP: {"has_calendar": True, "open_join": True},
    }

    kind = models.CharField(max_length=16, choices=Kind.choices)
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField(blank=True, help_text="Markdown supported.")

    landing_visibility = models.CharField(
        max_length=16,
        choices=Visibility.choices,
        default=Visibility.MEMBERS,
        help_text="Who can see that this group exists (its landing page).",
    )
    content_visibility = models.CharField(
        max_length=16,
        choices=Visibility.choices,
        default=Visibility.PRIVATE,
        help_text=(
            "Who can see the roster, works, and files. Cannot be more public "
            "than the landing visibility."
        ),
    )

    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(
        null=True, blank=True, help_text="Null for standing / ongoing groups."
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
        help_text="Optional parent group (e.g. a committee that spawned this).",
    )
    auto_member_role = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text=(
            "If set to a Profile role (e.g. 'analyst'), every active user with "
            "that role is automatically a member of this group — derived, no "
            "roster rows. Used for the Meeting of Analysts."
        ),
    )
    open_join = models.BooleanField(
        default=False,
        help_text=(
            "If set, any LSP member may join this group directly (one click, no "
            "approval or payment). Default for reading groups."
        ),
    )

    # Capability toggles — defaulted per kind at creation, fully editable after.
    has_channel = models.BooleanField(default=True)
    has_works = models.BooleanField(default=True)
    has_files = models.BooleanField(default=True)
    has_calendar = models.BooleanField(default=False)
    has_minutes = models.BooleanField(default=False)
    has_tasks = models.BooleanField(default=False)
    has_decisions = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("kind", "name")

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            self.slug = slugify(self.name)[:140]
        super().save(*args, **kwargs)

    def clean(self):
        if _VISIBILITY_RANK[self.content_visibility] > _VISIBILITY_RANK[self.landing_visibility]:
            raise ValidationError({
                "content_visibility": _(
                    "Content visibility can't be more public than the landing "
                    "page visibility."
                ),
            })

    def get_absolute_url(self) -> str:
        return reverse("workgroups:detail", args=[self.slug])

    @property
    def description_html(self) -> str:
        if not self.description:
            return ""
        import markdown
        from django.utils.safestring import mark_safe

        return mark_safe(markdown.markdown(
            self.description, extensions=["smarty", "sane_lists"], output_format="html5"
        ))

    @classmethod
    def kind_toggle_defaults(cls, kind) -> dict:
        """The capability-toggle seed for ``kind`` (over the field defaults)."""
        return dict(cls.KIND_TOGGLE_DEFAULTS.get(kind, {}))

    # ---- Roster ----

    def active_members(self):
        """Stored ``WorkgroupMembership`` rows (hand-managed roster). For the
        full roster including derived seminar registrants, use
        :meth:`participants`."""
        return self.memberships.filter(end_date__isnull=True).select_related("user")

    @staticmethod
    def _user_role(user):
        return getattr(getattr(user, "profile", None), "role", None)

    def is_member(self, user) -> bool:
        """*Active* membership — the access primitive the cross-cutting apps
        call (channel posting, current roster, full workspace).

        Stored memberships count for every kind (faculty, organizers, cartel
        members …). For a term-based offering (seminar / reading group), active
        members are the paid/comped registrants of the **current term** only —
        past-term registrants are not active; they must renew to participate
        (but keep read-only :meth:`has_archive_access`). Dispatched via the
        reverse ``events`` accessor so this app needn't import ``events``.
        """
        if not getattr(user, "is_authenticated", False):
            return False
        # Role-derived membership (e.g. every Analyst belongs to the Meeting of
        # Analysts) — automatic, no stored row.
        if self.auto_member_role and self._user_role(user) == self.auto_member_role:
            return True
        if self.memberships.filter(user=user, end_date__isnull=True).exists():
            return True
        # Term-based offerings: active = current term's paid/comped registrants.
        if self.kind in self.OFFERING_KINDS:
            term = self.current_term()
            return term is not None and term.has_access_registrant(user)
        return False

    def has_archive_access(self, user) -> bool:
        """Read-only access to the group's archive (past materials + channel
        history) for someone who attended *any* term — retained after their
        term ends. Active membership (:meth:`is_member`) requires renewing the
        current term; archive viewers may read but not post or participate."""
        if self.is_member(user):
            return True
        if not getattr(user, "is_authenticated", False):
            return False
        if self.kind in self.OFFERING_KINDS:
            return any(e.has_access_registrant(user) for e in self.events.all())
        return False

    def participants(self):
        """The full roster for enumeration surfaces (roster list, assignee
        pickers, member count): stored members ∪ derived seminar registrants,
        deduped by user (a stored row wins over a derived one). Returns
        :class:`Participant` objects so callers see a uniform ``.user`` /
        ``.role`` / ``.get_role_display()`` shape regardless of source."""
        seen: dict = {}
        for m in self.active_members():
            seen[m.user_id] = Participant(
                user=m.user, role=m.role,
                is_lead=m.role in WorkgroupMembership.LEAD_ROLES, membership=m,
            )
        # Role-derived members (e.g. all Analysts in the Meeting of Analysts).
        if self.auto_member_role:
            from django.contrib.auth import get_user_model

            users = (get_user_model().objects
                     .filter(profile__role=self.auto_member_role, is_active=True)
                     .select_related("profile"))
            for u in users:
                if u.pk not in seen:
                    seen[u.pk] = Participant(
                        user=u, role=WorkgroupMembership.Role.MEMBER, is_lead=False,
                    )
        # The ACTIVE roster of a term-based offering = the current term's
        # paid/comped registrants (past-term-only attendees are archive-only,
        # not on the active roster). A committee's organized-event registrants
        # are never its roster.
        derived_events = []
        if self.kind in self.OFFERING_KINDS:
            term = self.current_term()
            derived_events = [term] if term is not None else []
        for event in derived_events:
            for u in event.access_registrant_users():
                if u.pk not in seen:
                    seen[u.pk] = Participant(
                        user=u, role=WorkgroupMembership.Role.MEMBER, is_lead=False,
                    )
        return list(seen.values())

    def current_term(self):
        """For a term-based offering (seminar / reading group), the active-or-
        upcoming term Event — the cycle members register for (and renew each
        year). The soonest term that hasn't ended yet; ``None`` once a term
        ends and no next one is open (active membership lapses to archive-only).
        ``None`` for a free reading group (no term) or any other kind."""
        if self.kind not in self.OFFERING_KINDS:
            return None
        today = timezone.localdate()
        active = [e for e in self.events.all() if e.end_date and e.end_date >= today]
        if not active:
            return None
        return min(active, key=lambda e: e.start_date or today)

    def open_reading_group_term(self, *, start_date, end_date, fee):
        """Open a new annual term for this reading group — a published, open
        ``Event`` attached to this standing workgroup, with a single all-audience
        price tier. Members register + pay for it; ``current_term`` picks it up.
        Returns the term Event."""
        from decimal import Decimal

        from django.utils.text import slugify

        from events.models import Audience, Event, PriceTier, academic_year_of

        ay = academic_year_of(start_date)
        base = (slugify(f"{self.slug}-{ay}") or f"{self.slug}-term")[:190]
        slug, n = base, 2
        while Event.objects.filter(slug=slug).exists():
            slug = f"{base}-{n}"
            n += 1
        term = Event.objects.create(
            title=f"{self.name} {ay}"[:200], slug=slug,
            event_type=Event.Type.READING_GROUP,
            start_date=start_date, end_date=end_date,
            published=True, status=Event.Status.OPEN, workgroup=self,
        )
        PriceTier.objects.create(
            event=term, audience=Audience.ALL, base_amount=Decimal(fee)
        )
        return term

    def primary_event(self):
        """For an offering workgroup (seminar / reading group), the Event to
        feature on Overview: the soonest current/upcoming one (end_date today
        or later), else the most recent. ``None`` for non-offering workgroups
        (a committee organizes events but offers none) or if there are none."""
        if self.kind not in self.OFFERING_KINDS:
            return None
        events = list(self.events.all())
        if not events:
            return None
        today = timezone.localdate()
        upcoming = [e for e in events if e.end_date and e.end_date >= today]
        if upcoming:
            return min(upcoming, key=lambda e: e.start_date or today)
        return max(events, key=lambda e: e.start_date or today)

    # ---- Program membership by date overlap (standing groups) ----

    def effective_window(self):
        """The group's active ``(start, end)`` dates from its own fields;
        ``end`` is ``None`` for an ongoing group. ``start`` may be ``None`` if
        unset (then it overlaps no specific year)."""
        return self.start_date, self.end_date

    def overlaps_academic_year(self, year) -> bool:
        from events.models import academic_year_date_range

        start, end = self.effective_window()
        if start is None:
            return False
        ay_start, ay_end = academic_year_date_range(year)
        return start <= ay_end and (end is None or end >= ay_start)

    def program_year(self):
        """The most relevant academic year for this standing group's program
        link: the current AY if active now, else the AY it started in."""
        from events.models import academic_year_of, current_academic_year

        if self.start_date is None:
            return None
        now_year = current_academic_year()
        if self.overlaps_academic_year(now_year):
            return now_year
        return academic_year_of(self.start_date)

    def program_academic_year(self):
        """The academic-year label this group is grouped under in listings — its
        offering event's AY (seminar), its cartel's program year, or — for a
        standing reading group — its own date window. ``None`` if it belongs to
        no program year."""
        ev = self.primary_event()
        if ev is not None:
            return ev.academic_year
        try:
            cartel = self.cartel
        except ObjectDoesNotExist:
            cartel = None
        if cartel is not None:
            return cartel.program_year()
        if self.kind == self.Kind.READING_GROUP:
            return self.program_year()
        return None

    def generate_event(self, **kwargs):
        """Create an Event generated by this workgroup (Workgroup-primary model).

        For offering kinds, ``event_type`` defaults to the matching type and
        ``title`` to the group's name. Scheduling fields (start_date, end_date,
        slug) are the caller's to supply. Lazy import keeps the dependency
        pointing events → workgroups.
        """
        from events.models import Event

        type_for_kind = {
            self.Kind.SEMINAR: Event.Type.SEMINAR,
            self.Kind.READING_GROUP: Event.Type.READING_GROUP,
            self.Kind.CARTEL: Event.Type.CARTEL,
        }
        kwargs.setdefault("event_type", type_for_kind.get(self.kind, Event.Type.SEMINAR))
        kwargs.setdefault("title", self.name)
        return Event.objects.create(workgroup=self, **kwargs)

    # ---- Visibility ----

    def _visible_at(self, level, user) -> bool:
        if level == Visibility.PUBLIC:
            return True
        if level == Visibility.MEMBERS:
            return is_lsp_member(user)
        return self.is_member(user)  # PRIVATE

    #: Term-based offering kinds: a standing Workgroup with one or more term
    #: Events. Public landing once a term is published; ACTIVE membership =
    #: current term's paid/comped registrants (past-term attendees keep
    #: read-only archive access; see ``has_archive_access``). A *free* reading
    #: group has no term and uses ``open_join`` instead.
    OFFERING_KINDS = frozenset({Kind.SEMINAR, Kind.READING_GROUP})

    def _has_public_event(self) -> bool:
        if self.kind not in self.OFFERING_KINDS:
            return False
        return any(getattr(e, "is_public_now", False) for e in self.events.all())

    def landing_visible_to(self, user) -> bool:
        # A seminar / reading-group Workspace is the canonical page for its
        # offering: once the event is public, so is the landing (Overview shows
        # the public summary; content/roster stays gated by content_visibility).
        if self._has_public_event():
            return True
        return self._visible_at(self.landing_visibility, user)

    def content_visible_to(self, user) -> bool:
        return self._visible_at(self.content_visibility, user)

    #: Who may see a group's *membership list* (the roster), by kind —
    #: independent of ``content_visibility``. Committees and working groups are
    #: public; cartels and reading groups are open to any LSP member; seminars
    #: never show a student roster (their faculty appear via the attached
    #: event's summary instead).
    ROSTER_VISIBILITY = {
        Kind.COMMITTEE: Visibility.PUBLIC,
        Kind.WORKING_GROUP: Visibility.PUBLIC,
        Kind.CARTEL: Visibility.MEMBERS,
        Kind.READING_GROUP: Visibility.MEMBERS,
        Kind.SEMINAR: None,
    }

    def roster_visible_to(self, user) -> bool:
        """Whether ``user`` may see this group's membership list (see
        :attr:`ROSTER_VISIBILITY`). Page access is still gated by
        :meth:`landing_visible_to` — this only governs the roster itself."""
        level = self.ROSTER_VISIBILITY.get(self.kind)
        if level is None:           # seminar — no student roster, ever
            return False
        if self._visible_at(level, user):
            return True
        # A group's own members always see its roster.
        return self.is_member(user)

    # ---- Governance (propose → review → join), generalized from cartels ----

    def _add_member(self, user, *, role=None):
        """Idempotent: add ``user`` to the stored roster. Returns the active
        membership row (existing or newly created)."""
        if role is None:
            role = WorkgroupMembership.Role.MEMBER
        existing = self.memberships.filter(user=user, end_date__isnull=True).first()
        if existing:
            return existing
        return WorkgroupMembership.objects.create(
            workgroup=self, user=user, role=role, start_date=timezone.localdate(),
        )

    def request_to_join(self, user, message=""):
        """A member applies to join (member-gated growth). Idempotent on the
        pending request."""
        req, created = WorkgroupJoinRequest.objects.get_or_create(
            workgroup=self, applicant=user,
            status=WorkgroupJoinRequest.Status.PENDING,
            defaults={"message": message},
        )
        if not created and message and not req.message:
            req.message = message
            req.save(update_fields=["message"])
        return req

    def accept_request(self, join_request, decided_by):
        join_request.accept(decided_by)

    def decline_request(self, join_request, decided_by):
        join_request.decline(decided_by)

    def accept_invitation(self, user):
        """A seeded invitee joins directly. Returns the invitation, or ``None``
        if the user wasn't invited (or already accepted)."""
        inv = self.invitations.filter(
            invited_user=user, accepted_at__isnull=True
        ).first()
        if inv is None:
            return None
        inv.accept()
        return inv

    def governance_state(self, user) -> dict:
        """The proposal/join context shared by every governed kind — the
        generic subset of the cartel ``viewer_state`` (a concrete type layers
        its own keys on top)."""
        authed = getattr(user, "is_authenticated", False)
        try:
            proposal = self.proposal
        except ObjectDoesNotExist:
            proposal = None
        is_member = self.is_member(user)
        has_invite = bool(authed) and self.invitations.filter(
            invited_user=user, accepted_at__isnull=True
        ).exists()
        already_applied = bool(authed) and self.join_requests.filter(
            applicant=user, status=WorkgroupJoinRequest.Status.PENDING
        ).exists()
        is_open = proposal is not None and proposal.status == WorkgroupProposal.Status.OPEN
        can_apply = (
            is_open and is_lsp_member(user)
            and not is_member and not has_invite and not already_applied
        )
        pending = (
            list(self.join_requests.filter(status=WorkgroupJoinRequest.Status.PENDING)
                 .select_related("applicant"))
            if is_member else []
        )
        return {
            "has_invite": has_invite,
            "already_applied": already_applied,
            "can_apply": can_apply,
            "pending_requests": pending,
        }


class WorkgroupMembership(models.Model):
    """A user's tenure in a workgroup — the unified roster.

    Generalizes ``committees.CommitteeMembership`` (same shape, same
    one-active-per-pair constraint). The cartel "plus-one" is just
    ``role=PLUS_ONE`` — no field on the Cartel model.
    """

    class Role(models.TextChoices):
        MEMBER = "member", _("Member")
        CHAIR = "chair", _("Chair")
        CO_CHAIR = "co_chair", _("Co-chair")
        SECRETARY = "secretary", _("Secretary")
        TREASURER = "treasurer", _("Treasurer")
        PLUS_ONE = "plus_one", _("Plus-one")
        FACULTY = "faculty", _("Faculty")
        ORGANIZER = "organizer", _("Organizer")
        # Carried for the Stage-4 committee fold-in:
        REFERRAL_COORDINATOR = "referral_coordinator", _("Referral Coordinator")
        WEB_COORDINATOR = "web_coordinator", _("Web Coordinator")
        ADMIN_ASSISTANT = "admin_assistant", _("Admin Assistant")

    #: Roles that moderate a workgroup's channel (Stage 2) and manage it.
    #: Faculty lead their seminar's workspace; organizers lead a reading group.
    LEAD_ROLES = (Role.CHAIR, Role.CO_CHAIR, Role.PLUS_ONE, Role.FACULTY,
                  Role.ORGANIZER)

    workgroup = models.ForeignKey(
        Workgroup,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workgroup_memberships",
    )
    role = models.CharField(
        max_length=24,
        choices=Role.choices,
        default=Role.MEMBER,
    )
    start_date = models.DateField()
    end_date = models.DateField(
        null=True,
        blank=True,
        help_text="Null for currently-serving members.",
    )

    class Meta:
        ordering = ("workgroup__name", "-start_date")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "workgroup"),
                condition=models.Q(end_date__isnull=True),
                name="workgroups_one_active_membership_per_user_group",
            ),
        ]

    def __str__(self) -> str:
        active = "active" if self.end_date is None else f"ended {self.end_date.isoformat()}"
        return f"{self.user} — {self.workgroup} ({self.get_role_display()}, {active})"

    @property
    def is_active(self) -> bool:
        return self.end_date is None


class WorkgroupProposal(models.Model):
    """The governance record for a workgroup formed by proposal → review →
    publish (generalized from the cartel CART-4 flow).

    Holds the status + reviewer trail shared by every governed kind; a concrete
    type layers its own proposal payload on top (a cartel's guiding question, a
    seminar's proposed dates). One per workgroup.
    """

    class Status(models.TextChoices):
        PROPOSED = "proposed", _("Proposed — awaiting review")
        OPEN = "open", _("Open")
        DECLINED = "declined", _("Declined")
        ARCHIVED = "archived", _("Archived")

    workgroup = models.OneToOneField(
        Workgroup, on_delete=models.CASCADE, related_name="proposal",
    )
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="workgroup_proposals",
        help_text="The member who proposed the group.",
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PROPOSED,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="workgroup_proposals_reviewed",
        help_text="The reviewer (e.g. Program Committee) who approved / declined.",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True, help_text="Decline reason / review notes.")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.workgroup} — {self.get_status_display()}"

    @transaction.atomic
    def approve(self, reviewer, *, publish_visibility=Visibility.MEMBERS):
        """Approve → publish the landing as Open (visible to the school)."""
        self.status = self.Status.OPEN
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.workgroup.landing_visibility = publish_visibility
        self.workgroup.save(update_fields=["landing_visibility"])
        self.save(update_fields=["status", "reviewed_by", "reviewed_at"])

    @transaction.atomic
    def decline(self, reviewer, note=""):
        self.status = self.Status.DECLINED
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.review_note = note
        self.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note"])

    @transaction.atomic
    def resubmit(self):
        """A declined proposal, edited, re-enters review (and re-hides)."""
        if self.status != self.Status.DECLINED:
            return
        self.status = self.Status.PROPOSED
        self.reviewed_by = None
        self.reviewed_at = None
        self.review_note = ""
        self.workgroup.landing_visibility = Visibility.PRIVATE
        self.workgroup.save(update_fields=["landing_visibility"])
        self.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note"])


class WorkgroupInvitation(models.Model):
    """A specific-member invitation seeded by the proposer; accepting joins the
    group directly (generalized from the cartel's seeded invitations)."""

    workgroup = models.ForeignKey(
        Workgroup, on_delete=models.CASCADE, related_name="invitations",
    )
    invited_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="workgroup_invitations",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="workgroup_invitations_sent",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("workgroup", "invited_user"),
                name="workgroups_one_invitation_per_user",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.invited_user} invited to {self.workgroup}"

    @transaction.atomic
    def accept(self):
        self.workgroup._add_member(self.invited_user)
        self.accepted_at = timezone.now()
        self.save(update_fields=["accepted_at"])


class WorkgroupJoinRequest(models.Model):
    """An uninvited member's application to join an Open group; accepted or
    declined by an existing member (member-gated growth)."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        ACCEPTED = "accepted", _("Accepted")
        DECLINED = "declined", _("Declined")

    workgroup = models.ForeignKey(
        Workgroup, on_delete=models.CASCADE, related_name="join_requests",
    )
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="workgroup_join_requests",
    )
    message = models.TextField(
        blank=True, help_text="Why the applicant would like to join (shown to members)."
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="workgroup_join_decisions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("workgroup", "applicant"),
                condition=models.Q(status="pending"),
                name="workgroups_one_pending_request_per_user",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.applicant} → {self.workgroup} ({self.get_status_display()})"

    @transaction.atomic
    def accept(self, decided_by):
        self.workgroup._add_member(self.applicant)
        self.status = self.Status.ACCEPTED
        self.decided_by = decided_by
        self.decided_at = timezone.now()
        self.save(update_fields=["status", "decided_by", "decided_at"])

    def decline(self, decided_by):
        self.status = self.Status.DECLINED
        self.decided_by = decided_by
        self.decided_at = timezone.now()
        self.save(update_fields=["status", "decided_by", "decided_at"])


class WorkgroupTask(models.Model):
    """A shared to-do for a workgroup's Tasks tab (has_tasks). Supports
    multiple assignees and an optional due date."""

    workgroup = models.ForeignKey(
        Workgroup, on_delete=models.CASCADE, related_name="tasks"
    )
    title = models.CharField(max_length=255)
    done = models.BooleanField(default=False)
    assignees = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="assigned_workgroup_tasks",
    )
    due_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True, on_delete=models.SET_NULL,
        related_name="created_workgroup_tasks",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        # Open tasks first, soonest due date first (nulls last), then newest.
        ordering = ("done", "-created_at")

    def __str__(self) -> str:
        return self.title

    def set_done(self, value: bool):
        self.done = bool(value)
        self.completed_at = timezone.now() if value else None
        self.save(update_fields=["done", "completed_at"])

    @property
    def is_overdue(self) -> bool:
        return bool(self.due_date and not self.done
                    and self.due_date < timezone.localdate())


class WorkgroupMeeting(models.Model):
    """A scheduled meeting / session for a workgroup's Schedule tab
    (has_calendar). Lightweight and internal — distinct from public Events."""

    workgroup = models.ForeignKey(
        Workgroup, on_delete=models.CASCADE, related_name="meetings"
    )
    title = models.CharField(max_length=255, blank=True, help_text="Optional label.")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    location = models.CharField(
        max_length=255, blank=True, help_text="Room or video link."
    )
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True, on_delete=models.SET_NULL,
        related_name="created_workgroup_meetings",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("starts_at",)

    def __str__(self) -> str:
        return f"{self.title or 'Meeting'} — {self.starts_at:%Y-%m-%d %H:%M}"

    @property
    def is_past(self) -> bool:
        return self.starts_at < timezone.now()


def build_workgroup(kind, *, name, **kwargs):
    """Create a Workgroup of ``kind`` with its per-kind capability seed applied.

    The seed fills any toggle the caller didn't pass explicitly. Shared by the
    concrete group types' ``create_with_workgroup`` helpers so the creation
    logic lives on the Workgroup side (add-to-Workgroup-first principle).
    """
    toggles = Workgroup.kind_toggle_defaults(kind)
    # Reading groups have a public landing (like seminars) so prospective
    # members can see the page; the roster + content stay members-only.
    if kind == Workgroup.Kind.READING_GROUP:
        toggles.setdefault("landing_visibility", Visibility.PUBLIC)
        toggles.setdefault("content_visibility", Visibility.MEMBERS)
    toggles.update(kwargs)
    return Workgroup.objects.create(kind=kind, name=name, **toggles)
