"""Cartels — the first concrete group type on the shared Workgroup layer.

A cartel *attaches* a :class:`workgroups.Workgroup` (which holds the roster,
channel, works, files, and landing page). ``Cartel`` adds only the
cartel-specific bits: the guiding question and the CART-4 formation/joining
workflow (propose → Coordinator review → publish Open → solicit → apply →
member-gated growth). The Lacanian plus-one is a ``WorkgroupMembership`` role,
not a field here; the cartel's "product" is a group-visible Work.

See ../LSP-Website-Cartels-Design.md.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from workgroups.models import Workgroup, WorkgroupMembership, build_workgroup


class CartelManager(models.Manager):
    @transaction.atomic
    def create_with_workgroup(self, *, name, **workgroup_kwargs):
        """Low-level: create a Cartel + its backing Workgroup (no workflow)."""
        wg = build_workgroup(Workgroup.Kind.CARTEL, name=name, **workgroup_kwargs)
        return self.create(workgroup=wg)

    @transaction.atomic
    def propose(self, *, generator, name, guiding_question="", description="", invitees=()):
        """A member proposes a cartel (CART-4 step 1).

        Creates a PROPOSED cartel (landing private until approved); the
        Generator is its first member; any seeded ``invitees`` become
        CartelInvitations sent on approval.
        """
        wg = build_workgroup(
            Workgroup.Kind.CARTEL,
            name=name,
            description=description,
            landing_visibility="private",   # hidden until the Coordinator approves
            content_visibility="private",
        )
        cartel = self.create(
            workgroup=wg,
            generator=generator,
            guiding_question=guiding_question,
            status=Cartel.Status.PROPOSED,
        )
        cartel.add_member(generator)
        for user in invitees:
            CartelInvitation.objects.get_or_create(cartel=cartel, invited_user=user)
        return cartel

    def in_academic_year(self, year):
        """Open / Archived cartels whose active window overlaps academic year
        ``year`` — i.e. that *existed at any point* during it. These are listed
        on that year's program (a cartel can span several years). Newest first.
        """
        from events.models import academic_year_date_range

        ay_start, ay_end = academic_year_date_range(year)
        out = [
            c for c in self.filter(
                status__in=(Cartel.Status.OPEN, Cartel.Status.ARCHIVED)
            ).select_related("workgroup")
            if c._window_overlaps(ay_start, ay_end)
        ]
        out.sort(key=lambda c: c.effective_window()[0], reverse=True)
        return out


class Cartel(models.Model):
    class Status(models.TextChoices):
        PROPOSED = "proposed", _("Proposed — awaiting Coordinator review")
        OPEN = "open", _("Open — soliciting membership")
        DECLINED = "declined", _("Declined")
        ARCHIVED = "archived", _("Archived")

    workgroup = models.OneToOneField(
        Workgroup,
        on_delete=models.CASCADE,
        related_name="cartel",
    )
    guiding_question = models.TextField(
        blank=True, help_text="The question the cartel forms around."
    )
    generator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cartels_generated",
        help_text="The member who proposed the cartel.",
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PROPOSED
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cartels_reviewed",
        help_text="The Program Committee member who approved / declined.",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True, help_text="Decline reason / PC review notes.")
    coordinator_feedback = models.TextField(
        blank=True,
        help_text="Cartel Coordinator's feedback / advocacy (advisory — the "
        "Program Committee approves).",
    )
    closed = models.BooleanField(
        default=False, help_text="Closed to new members (members may toggle)."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = CartelManager()

    def __str__(self) -> str:
        return self.workgroup.name

    def get_absolute_url(self) -> str:
        # The cartel's canonical page is the generic Workgroup detail
        # (/groups/<slug>/), which composes the cartel actions partial.
        return self.workgroup.get_absolute_url()

    # ---- Program membership (by date overlap — cartels self-form, no FK) ----

    def effective_window(self):
        """The cartel's active (start, end) dates. Falls back to its review /
        creation date when no explicit start is set; ``end`` is ``None`` for an
        open-ended (ongoing) cartel."""
        wg = self.workgroup
        start = wg.start_date or (self.reviewed_at or self.created_at).date()
        return start, wg.end_date

    def _window_overlaps(self, range_start, range_end) -> bool:
        start, end = self.effective_window()
        return start <= range_end and (end is None or end >= range_start)

    def overlaps_academic_year(self, year) -> bool:
        from events.models import academic_year_date_range

        return self._window_overlaps(*academic_year_date_range(year))

    def program_year(self):
        """The most relevant academic year for this cartel's program link: the
        current AY if the cartel is active now, else the AY it started in."""
        from events.models import academic_year_of, current_academic_year

        now_year = current_academic_year()
        if self.overlaps_academic_year(now_year):
            return now_year
        return academic_year_of(self.effective_window()[0])

    def viewer_state(self, user) -> dict:
        """Cartel-specific context for the (generic) detail page — so the
        workgroups detail view can compose cartel UI via this one call,
        without importing the cartels app."""
        from accounts.permissions import is_lsp_member

        authed = getattr(user, "is_authenticated", False)
        is_member = self.is_member(user)
        has_invite = bool(authed) and self.invitations.filter(
            invited_user=user, accepted_at__isnull=True
        ).exists()
        already_applied = bool(authed) and self.join_requests.filter(
            applicant=user, status=CartelJoinRequest.Status.PENDING
        ).exists()
        can_apply = (
            self.status == self.Status.OPEN and not self.closed
            and is_lsp_member(user) and not is_member and not has_invite and not already_applied
        )
        pending = (
            list(self.join_requests.filter(status=CartelJoinRequest.Status.PENDING)
                 .select_related("applicant"))
            if is_member else []
        )
        return {
            "has_invite": has_invite,
            "already_applied": already_applied,
            "can_apply": can_apply,
            "pending_requests": pending,
            "is_generator": bool(authed) and self.generator_id == user.id,
        }

    # ---- Membership ----

    def is_member(self, user) -> bool:
        return self.workgroup.is_member(user)

    def add_member(self, user, *, plus_one=False):
        """Idempotent: add ``user`` to the cartel's roster (workgroup)."""
        role = WorkgroupMembership.Role.PLUS_ONE if plus_one else WorkgroupMembership.Role.MEMBER
        existing = self.workgroup.memberships.filter(user=user, end_date__isnull=True).first()
        if existing:
            return existing
        return WorkgroupMembership.objects.create(
            workgroup=self.workgroup, user=user, role=role,
            start_date=timezone.now().date(),
        )

    # ---- CART-4 workflow ----

    @transaction.atomic
    def approve(self, coordinator):
        """Coordinator approves → publish as Open (CART-4 steps 2–3)."""
        self.status = self.Status.OPEN
        self.reviewed_by = coordinator
        self.reviewed_at = timezone.now()
        self.workgroup.landing_visibility = "members"   # visible to the school to solicit
        self.workgroup.save(update_fields=["landing_visibility"])
        self.save(update_fields=["status", "reviewed_by", "reviewed_at"])

    @transaction.atomic
    def decline(self, coordinator, note=""):
        self.status = self.Status.DECLINED
        self.reviewed_by = coordinator
        self.reviewed_at = timezone.now()
        self.review_note = note
        self.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note"])

    @transaction.atomic
    def resubmit(self):
        """A declined proposal is re-submitted (after edits) for fresh review."""
        if self.status != self.Status.DECLINED:
            return
        self.status = self.Status.PROPOSED
        self.reviewed_by = None
        self.reviewed_at = None
        self.review_note = ""
        self.workgroup.landing_visibility = "private"   # hidden again until re-approved
        self.workgroup.save(update_fields=["landing_visibility"])
        self.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note"])

    def set_closed(self, value: bool):
        self.closed = bool(value)
        self.save(update_fields=["closed"])

    def archive(self):
        self.status = self.Status.ARCHIVED
        self.save(update_fields=["status"])

    def set_internal_plus_one(self, user):
        """Designate an LSP-member plus-one: demote any existing internal
        plus-one to member, then set ``user`` as the plus-one (joining if
        needed)."""
        lead = WorkgroupMembership.Role
        self.workgroup.memberships.filter(
            role=lead.PLUS_ONE, end_date__isnull=True
        ).exclude(user=user).update(role=lead.MEMBER)
        m = self.workgroup.memberships.filter(user=user, end_date__isnull=True).first()
        if m:
            if m.role != lead.PLUS_ONE:
                m.role = lead.PLUS_ONE
                m.save(update_fields=["role"])
            return m
        return self.add_member(user, plus_one=True)

    def accept_invitation(self, user):
        """A seeded invitee joins directly (Generator pre-approved them)."""
        inv = self.invitations.filter(invited_user=user, accepted_at__isnull=True).first()
        if inv is None:
            return None
        self.add_member(user)
        inv.accepted_at = timezone.now()
        inv.save(update_fields=["accepted_at"])
        return inv

    def request_to_join(self, user, message=""):
        """An uninvited member applies (CART-4 step 5), with a note on why."""
        req, created = CartelJoinRequest.objects.get_or_create(
            cartel=self, applicant=user, status=CartelJoinRequest.Status.PENDING,
            defaults={"message": message},
        )
        if not created and message and not req.message:
            req.message = message
            req.save(update_fields=["message"])
        return req

    @transaction.atomic
    def accept_request(self, join_request, decided_by):
        """An existing member accepts an applicant (CART-4 step 6)."""
        self.add_member(join_request.applicant)
        join_request.status = CartelJoinRequest.Status.ACCEPTED
        join_request.decided_by = decided_by
        join_request.decided_at = timezone.now()
        join_request.save(update_fields=["status", "decided_by", "decided_at"])

    def decline_request(self, join_request, decided_by):
        join_request.status = CartelJoinRequest.Status.DECLINED
        join_request.decided_by = decided_by
        join_request.decided_at = timezone.now()
        join_request.save(update_fields=["status", "decided_by", "decided_at"])


class CartelInvitation(models.Model):
    """A specific-member invitation seeded by the Generator (the "special
    invitations" sent on approval). Accepting joins the cartel directly."""

    cartel = models.ForeignKey(Cartel, on_delete=models.CASCADE, related_name="invitations")
    invited_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cartel_invitations"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("cartel", "invited_user"), name="cartels_one_invitation_per_user",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.invited_user} invited to {self.cartel}"


class ExternalPlusOne(models.Model):
    """An external (non-LSP) plus-one for a cartel — modeled on
    ``events.Speaker``. The cartel may invite them to create an account, which
    converts them to a normal internal plus-one when they sign up."""

    cartel = models.ForeignKey(Cartel, on_delete=models.CASCADE, related_name="external_plus_ones")
    name = models.CharField(max_length=200)
    affiliation = models.CharField(max_length=200, blank=True)
    bio = models.TextField(blank=True)
    email = models.EmailField(blank=True, help_text="Used to invite account creation.")
    invited_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.name} (plus-one, external) — {self.cartel}"


class CartelJoinRequest(models.Model):
    """An uninvited member's application to join an Open cartel; accepted or
    declined by an existing member (member-gated growth)."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        ACCEPTED = "accepted", _("Accepted")
        DECLINED = "declined", _("Declined")

    cartel = models.ForeignKey(Cartel, on_delete=models.CASCADE, related_name="join_requests")
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cartel_join_requests"
    )
    message = models.TextField(
        blank=True, help_text="Why the applicant would like to join (shown to members)."
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="cartel_join_decisions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("cartel", "applicant"),
                condition=models.Q(status="pending"),
                name="cartels_one_pending_request_per_user",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.applicant} → {self.cartel} ({self.get_status_display()})"
