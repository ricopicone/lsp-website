"""Cartels — the first concrete group type on the shared Workgroup layer.

A cartel *attaches* a :class:`workgroups.Workgroup` (which holds the roster,
channel, works, files, and landing page). ``Cartel`` adds only the
cartel-specific bits: the guiding question and the Cartel-Coordinator feedback.
The CART-4 formation/joining workflow (propose → review → publish Open →
solicit → apply → member-gated growth) now lives generically on the Workgroup
layer (``WorkgroupProposal`` / ``WorkgroupInvitation`` / ``WorkgroupJoinRequest``);
``Cartel`` delegates to it. The Lacanian plus-one is a ``WorkgroupMembership``
role, not a field here; the cartel's "product" is a group-visible Work.

See ../LSP-Website-Cartels-Design.md and docs/design-group-governance.md.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from workgroups.models import (
    Workgroup,
    WorkgroupInvitation,
    WorkgroupJoinRequest,
    WorkgroupMembership,
    WorkgroupProposal,
    build_workgroup,
)


class CartelManager(models.Manager):
    @transaction.atomic
    def create_with_workgroup(self, *, name, **workgroup_kwargs):
        """Low-level: create a Cartel + its backing Workgroup (no workflow).

        Records an Open proposal so the cartel has a coherent governance status
        from the start (these are directly-created, already-active cartels)."""
        wg = build_workgroup(Workgroup.Kind.CARTEL, name=name, **workgroup_kwargs)
        WorkgroupProposal.objects.create(workgroup=wg, status=WorkgroupProposal.Status.OPEN)
        return self.create(workgroup=wg)

    @transaction.atomic
    def propose(self, *, generator, name, guiding_question="", description="", invitees=()):
        """A member starts a cartel forming (task #392 step 1).

        The cartel is live among the school immediately (members-visible landing,
        private contents); the generator is its first member; seeded ``invitees``
        become WorkgroupInvitations. PC registration happens later, on submit.
        """
        wg = build_workgroup(
            Workgroup.Kind.CARTEL,
            name=name,
            description=description,
            landing_visibility="members",   # visible to the school while forming
            content_visibility="private",
        )
        WorkgroupProposal.objects.create(
            workgroup=wg, proposed_by=generator,
            status=WorkgroupProposal.Status.OPEN,
        )
        cartel = self.create(
            workgroup=wg, guiding_question=guiding_question,
            registration_status=self.model.RegistrationStatus.FORMING,
        )
        cartel.add_member(generator)
        for user in invitees:
            WorkgroupInvitation.objects.get_or_create(
                workgroup=wg, invited_user=user, defaults={"created_by": generator},
            )
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
                workgroup__proposal__status__in=(
                    WorkgroupProposal.Status.OPEN, WorkgroupProposal.Status.ARCHIVED,
                )
            ).select_related("workgroup", "workgroup__proposal")
            if c._window_overlaps(ay_start, ay_end)
        ]
        out.sort(key=lambda c: c.effective_window()[0], reverse=True)
        return out


class Cartel(models.Model):
    #: Alias so existing ``Cartel.Status.OPEN`` references keep working — the
    #: status now lives on the workgroup's :class:`WorkgroupProposal`.
    Status = WorkgroupProposal.Status

    class RegistrationStatus(models.TextChoices):
        FORMING = "forming", "Forming — gathering members"
        SUBMITTED = "submitted", "Submitted for PC registration"
        REGISTERED = "registered", "Registered — approved by the PC"

    workgroup = models.OneToOneField(
        Workgroup,
        on_delete=models.CASCADE,
        related_name="cartel",
    )
    guiding_question = models.TextField(
        blank=True, help_text="The question the cartel forms around."
    )
    coordinator_feedback = models.TextField(
        blank=True,
        help_text="Cartel Coordinator's feedback / advocacy (advisory — the "
        "Program Committee approves).",
    )
    closed = models.BooleanField(
        default=False, help_text="Closed to new members (members may toggle)."
    )
    registration_status = models.CharField(
        max_length=10,
        choices=RegistrationStatus.choices,
        default=RegistrationStatus.FORMING,
        help_text="Where the cartel sits in the formation → PC-registration flow.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = CartelManager()

    def __str__(self) -> str:
        return self.workgroup.name

    def get_absolute_url(self) -> str:
        # The cartel's canonical page is the generic Workgroup detail
        # (/groups/<slug>/), which composes the cartel actions partial.
        return self.workgroup.get_absolute_url()

    # ---- Proposal proxies (status / generator / review live on the proposal) ----

    @property
    def proposal(self):
        return self.workgroup.proposal

    @property
    def status(self):
        return self.workgroup.proposal.status

    def get_status_display(self):
        return self.workgroup.proposal.get_status_display()

    @property
    def generator(self):
        return self.workgroup.proposal.proposed_by

    @property
    def generator_id(self):
        return self.workgroup.proposal.proposed_by_id

    @property
    def reviewed_by(self):
        return self.workgroup.proposal.reviewed_by

    @property
    def reviewed_at(self):
        return self.workgroup.proposal.reviewed_at

    @property
    def review_note(self):
        return self.workgroup.proposal.review_note

    @property
    def invitations(self):
        return self.workgroup.invitations

    @property
    def join_requests(self):
        return self.workgroup.join_requests

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
        """Cartel-specific context for the (generic) detail page — composes the
        shared :meth:`Workgroup.governance_state` and layers the cartel's
        ``closed`` gate and ``is_generator`` flag on top."""
        state = self.workgroup.governance_state(user)
        state["can_apply"] = state["can_apply"] and not self.closed
        authed = getattr(user, "is_authenticated", False)
        state["is_generator"] = (
            bool(authed) and self.generator_id is not None and self.generator_id == user.id
        )
        return state

    # ---- Membership ----

    def is_member(self, user) -> bool:
        return self.workgroup.is_member(user)

    def add_member(self, user, *, plus_one=False):
        """Idempotent: add ``user`` to the cartel's roster (workgroup)."""
        role = WorkgroupMembership.Role.PLUS_ONE if plus_one else WorkgroupMembership.Role.MEMBER
        return self.workgroup._add_member(user, role=role)

    # ---- CART-4 workflow (delegates to the generic proposal) ----

    @transaction.atomic
    def approve(self, reviewer):
        """The Programming Committee registers the cartel (task #392 step 5)."""
        self.registration_status = self.RegistrationStatus.REGISTERED
        self.save(update_fields=["registration_status"])
        proposal = self.workgroup.proposal
        proposal.reviewed_by = reviewer
        proposal.reviewed_at = timezone.now()
        proposal.review_note = ""
        proposal.save(update_fields=["reviewed_by", "reviewed_at", "review_note"])

    @transaction.atomic
    def decline(self, reviewer, note=""):
        """The PC returns the cartel for revision — it keeps forming and may be
        resubmitted."""
        self.registration_status = self.RegistrationStatus.FORMING
        self.save(update_fields=["registration_status"])
        proposal = self.workgroup.proposal
        proposal.reviewed_by = reviewer
        proposal.reviewed_at = timezone.now()
        proposal.review_note = note
        proposal.save(update_fields=["reviewed_by", "reviewed_at", "review_note"])

    def set_closed(self, value: bool):
        self.closed = bool(value)
        self.save(update_fields=["closed"])

    def archive(self, by=None):
        proposal = self.workgroup.proposal
        proposal.status = proposal.Status.ARCHIVED
        proposal.save(update_fields=["status"])
        # Freeze the workspace read-only too (the shared lifecycle archive),
        # while keeping the cartel listed on its program year by proposal status.
        self.workgroup.archive(by=by)

    def unarchive(self, by=None):
        """Exhume an archived cartel: reopen its proposal and un-freeze the
        workspace so members can post and grow it again."""
        proposal = self.workgroup.proposal
        proposal.status = proposal.Status.OPEN
        proposal.save(update_fields=["status"])
        self.workgroup.unarchive(by=by)

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

    def clear_internal_plus_one(self):
        """Unset the internal plus-one: demote whoever currently holds the role
        back to an ordinary member (they stay in the cartel)."""
        lead = WorkgroupMembership.Role
        self.workgroup.memberships.filter(
            role=lead.PLUS_ONE, end_date__isnull=True
        ).update(role=lead.MEMBER)

    def accept_invitation(self, user):
        """A seeded invitee joins directly (Generator pre-approved them)."""
        return self.workgroup.accept_invitation(user)

    def request_to_join(self, user, message=""):
        """An uninvited member applies (CART-4 step 5), with a note on why."""
        return self.workgroup.request_to_join(user, message)

    @transaction.atomic
    def accept_request(self, join_request, decided_by):
        """An existing member accepts an applicant (CART-4 step 6)."""
        self.workgroup.accept_request(join_request, decided_by)

    def decline_request(self, join_request, decided_by):
        self.workgroup.decline_request(join_request, decided_by)

    # ---- Registration (submit-to-PC) gate ----

    #: Cartel size bounds (cartelisands; the plus-one is extra).
    MIN_CARTELISANDS = 3
    MAX_CARTELISANDS = 5

    def cartelisand_count(self) -> int:
        """Active members excluding whoever holds the plus-one role."""
        return self.workgroup.memberships.serving().exclude(
            role=WorkgroupMembership.Role.PLUS_ONE
        ).count()

    def has_plus_one(self) -> bool:
        internal = self.workgroup.memberships.serving().filter(
            role=WorkgroupMembership.Role.PLUS_ONE
        ).exists()
        return internal or self.external_plus_ones.exists()

    def duration_ok(self) -> bool:
        start, end = self.workgroup.start_date, self.workgroup.end_date
        if not (start and end):
            return False
        days = (end - start).days
        return 365 <= days <= 731

    def registration_checklist(self) -> dict:
        count = self.cartelisand_count()
        plus_one = self.has_plus_one()
        duration = self.duration_ok()
        in_range = self.MIN_CARTELISANDS <= count <= self.MAX_CARTELISANDS
        total = count
        done = self.member_questions.exclude(text="").count()
        return {
            "plus_one": plus_one,
            "duration": duration,
            "count": in_range,
            "count_value": count,
            "questions_done": done,
            "questions_total": total,
            "can_submit": bool(plus_one and duration and in_range),
        }

    @transaction.atomic
    def submit_for_registration(self, by):
        """Any cartelisand submits the cartel to the PC for registration once
        the required gate passes (questions stay optional)."""
        if not self.registration_checklist()["can_submit"]:
            raise ValidationError("The cartel is not ready to submit for registration.")
        self.registration_status = self.RegistrationStatus.SUBMITTED
        self.save(update_fields=["registration_status"])
        proposal = self.workgroup.proposal
        if proposal.review_note or proposal.reviewed_by_id:
            proposal.review_note = ""
            proposal.reviewed_by = None
            proposal.reviewed_at = None
            proposal.save(update_fields=["review_note", "reviewed_by", "reviewed_at"])


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


class CartelQuestion(models.Model):
    """A cartelisand's individual question — the unique angle each member takes
    on the cartel's theme, managed by that member as the cartel evolves. Every
    member of the cartel can read all questions; each edits only their own."""

    cartel = models.ForeignKey(
        Cartel, on_delete=models.CASCADE, related_name="member_questions"
    )
    member = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="cartel_questions"
    )
    text = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("cartel", "member"), name="cartels_one_question_per_member"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.member} — question in {self.cartel}"


# The cartel's invitations and join-requests now live on the Workgroup layer.
# Keep the old names importable so existing call sites and tests resolve them.
CartelInvitation = WorkgroupInvitation
CartelJoinRequest = WorkgroupJoinRequest
