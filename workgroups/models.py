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
from django.core.exceptions import ValidationError
from django.db import models
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
        Kind.READING_GROUP: {"has_calendar": True},
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

    def is_member(self, user) -> bool:
        """The single access primitive the cross-cutting apps call.

        Stored memberships are checked uniformly first — that covers
        hand-managed members for every kind, including a seminar's *faculty*
        (``role=FACULTY``). For an offering workgroup (seminar / reading group)
        access also flows from a paid/comped Registration on any attached
        ``Event``; that population stays *derived* (computed from the
        authoritative payment state, never stored as rows). Dispatched via the
        reverse ``events`` accessor so this app needn't import ``events``.
        """
        if not getattr(user, "is_authenticated", False):
            return False
        if self.memberships.filter(user=user, end_date__isnull=True).exists():
            return True
        # Derive from registrations ONLY for offering workgroups, whose
        # attached event IS the group. A committee merely *organizes* events
        # (they link to its workgroup), so its registrants must NOT become
        # committee members — that would leak its private channel.
        if self.kind not in self.OFFERING_KINDS:
            return False
        # Event counts per group are tiny, so the per-event check is cheap.
        return any(e.has_access_registrant(user) for e in self.events.all())

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
        # Derived registrants only for offering workgroups (see ``is_member``) —
        # a committee's organized-event registrants are not its roster.
        if self.kind in self.OFFERING_KINDS:
            for event in self.events.all():
                for u in event.access_registrant_users():
                    if u.pk not in seen:
                        seen[u.pk] = Participant(
                            user=u, role=WorkgroupMembership.Role.MEMBER, is_lead=False,
                        )
        return list(seen.values())

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

    #: Kinds whose Workspace is the public face of a registerable offering —
    #: its landing is publicly visible once the generated event is published.
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
        # Carried for the Stage-4 committee fold-in:
        REFERRAL_COORDINATOR = "referral_coordinator", _("Referral Coordinator")
        WEB_COORDINATOR = "web_coordinator", _("Web Coordinator")
        ADMIN_ASSISTANT = "admin_assistant", _("Admin Assistant")

    #: Roles that moderate a workgroup's channel (Stage 2) and manage it.
    #: Faculty lead their seminar's workspace, so they moderate it too.
    LEAD_ROLES = (Role.CHAIR, Role.CO_CHAIR, Role.PLUS_ONE, Role.FACULTY)

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
    toggles.update(kwargs)
    return Workgroup.objects.create(kind=kind, name=name, **toggles)
