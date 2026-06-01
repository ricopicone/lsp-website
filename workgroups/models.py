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
        return self.memberships.filter(end_date__isnull=True).select_related("user")

    def is_member(self, user) -> bool:
        """The single access primitive the cross-cutting apps call.

        For self-managed kinds this reads ``WorkgroupMembership``. A seminar
        workgroup derives its roster from the attached ``Event`` (faculty +
        paid/comped registrants) — dispatched via the reverse ``event``
        accessor so this app needn't import ``events``.
        """
        if not getattr(user, "is_authenticated", False):
            return False
        events = list(self.events.all())
        if events:
            # Offering workgroup: a member of any generated event's roster
            # (faculty + paid/comped registrants). Event counts per group are
            # tiny, so the per-event check is cheap.
            return any(e.is_workgroup_member(user) for e in events)
        return self.memberships.filter(
            user=user, end_date__isnull=True
        ).exists()

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

    def landing_visible_to(self, user) -> bool:
        return self._visible_at(self.landing_visibility, user)

    def content_visible_to(self, user) -> bool:
        return self._visible_at(self.content_visibility, user)


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
        # Carried for the Stage-4 committee fold-in:
        REFERRAL_COORDINATOR = "referral_coordinator", _("Referral Coordinator")
        WEB_COORDINATOR = "web_coordinator", _("Web Coordinator")
        ADMIN_ASSISTANT = "admin_assistant", _("Admin Assistant")

    #: Roles that moderate a workgroup's channel (Stage 2) and manage it.
    LEAD_ROLES = (Role.CHAIR, Role.CO_CHAIR, Role.PLUS_ONE)

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
    """A simple shared to-do for a workgroup's Tasks tab (has_tasks)."""

    workgroup = models.ForeignKey(
        Workgroup, on_delete=models.CASCADE, related_name="tasks"
    )
    title = models.CharField(max_length=255)
    done = models.BooleanField(default=False)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True, on_delete=models.SET_NULL,
        related_name="assigned_workgroup_tasks",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True, on_delete=models.SET_NULL,
        related_name="created_workgroup_tasks",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("done", "-created_at")

    def __str__(self) -> str:
        return self.title

    def set_done(self, value: bool):
        self.done = bool(value)
        self.completed_at = timezone.now() if value else None
        self.save(update_fields=["done", "completed_at"])


def build_workgroup(kind, *, name, **kwargs):
    """Create a Workgroup of ``kind`` with its per-kind capability seed applied.

    The seed fills any toggle the caller didn't pass explicitly. Shared by the
    concrete group types' ``create_with_workgroup`` helpers so the creation
    logic lives on the Workgroup side (add-to-Workgroup-first principle).
    """
    toggles = Workgroup.kind_toggle_defaults(kind)
    toggles.update(kwargs)
    return Workgroup.objects.create(kind=kind, name=name, **toggles)
