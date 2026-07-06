"""Advancement within formation — the ongoing-formation domain.

Extracted from :mod:`admissions.models`. The intake side (Application /
interviews / review) stays in ``admissions``; the ongoing-formation *advancement*
demandes live here. ``Advancement`` keeps its original database table
(``admissions_advancement``) so the move is state-only — no data migration.

The later formation steps (palimpsest: Precandidate → Candidate; passage:
Candidate → Analyst/Scholar) are :class:`Advancement` demandes, recommended by
the member's Advisor and decided by the Meeting of the Analysts. Every role
change routes through ``accounts.membership.record_membership_change``.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from admissions.storage import cv_storage


def step_label_for(kind, role) -> str:
    """The track-aware display name for a formation step. ``Palimpsest`` is the
    same on both tracks; the passage step is a **Passage** for the Analyst track
    and a **Traversée** for the Scholar track."""
    if kind == "palimpsest":
        return "Palimpsest"
    from accounts.models import Profile
    return "Traversée" if role in Profile.SCHOLAR_TRACK_ROLES else "Passage"


class Advancement(models.Model):
    """A member's demande to advance a step in formation.

    **Palimpsest** (Precandidate → Candidate) is the step built first; the model
    is generic so **Passage / Traversée** (Candidate → Analyst / Scholar) reuses
    it. Flow: the member opens a demande → their Advisor writes a recommendation
    and **presents it to the Meeting of the Analysts** (reminder emails nudge the
    Advisor until they do) → the Meeting decides. Approval advances the member's
    role via ``accounts.membership.record_membership_change``.
    """

    class Kind(models.TextChoices):
        PALIMPSEST = "palimpsest", _("Palimpsest (Precandidate → Candidate)")
        PASSAGE = "passage", _("Passage / Traversée (Candidate → Analyst / Scholar)")

    class Status(models.TextChoices):
        REQUESTED = "requested", _("Requested — awaiting advisor's recommendation")
        PRESENTED = "presented", _("Presented to the Meeting of the Analysts")
        APPROVED = "approved", _("Approved")
        DECLINED = "declined", _("Not approved")
        WITHDRAWN = "withdrawn", _("Withdrawn")

    #: The formation step a member at a given role is requesting.
    KIND_FOR_ROLE = {
        "pre_candidate": Kind.PALIMPSEST,
        "pre_candidate_scholar": Kind.PALIMPSEST,
        "candidate": Kind.PASSAGE,
        "candidate_scholar": Kind.PASSAGE,
    }
    #: current role → role advanced into, per kind.
    ADVANCE_ROLE = {
        Kind.PALIMPSEST: {
            "pre_candidate": "candidate",
            "pre_candidate_scholar": "candidate_scholar",
        },
        Kind.PASSAGE: {
            "candidate": "analyst",
            "candidate_scholar": "scholar",
        },
    }
    OPEN_STATUSES = (Status.REQUESTED, Status.PRESENTED)

    member = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="advancements",
    )
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.PALIMPSEST)
    #: The role the member held when they opened the demande — the basis for
    #: ``advance_role`` (so a later role edit can't silently change the target).
    from_role = models.CharField(max_length=32)

    # The demande
    statement = models.TextField(
        help_text="The member's statement — why they are ready for this step.",
    )
    palimpsest = models.FileField(
        upload_to="palimpsest/%Y/", storage=cv_storage, blank=True,
        help_text="Optional written palimpsest / supporting document (private).",
    )

    # Advisor recommendation + presentation to the Meeting
    advisor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="advancements_advised",
        help_text="The member's Advisor at the time of the demande.",
    )
    recommendation = models.TextField(
        blank=True, help_text="The Advisor's recommendation to the Meeting.",
    )
    presented_at = models.DateField(
        null=True, blank=True,
        help_text="Date the Advisor presented the demande to the Meeting "
        "of the Analysts; blank = not yet presented.",
    )
    last_reminded_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When the Advisor was last reminded to present (reminder cron).",
    )

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.REQUESTED, db_index=True,
    )
    requested_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="advancement_decisions",
    )
    decision_note = models.TextField(blank=True)
    staff_notes = models.TextField(blank=True, help_text="Internal reviewer notes.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "admissions_advancement"
        ordering = ("-requested_at",)
        constraints = [
            # One open demande per member at a time.
            models.UniqueConstraint(
                fields=("member",),
                condition=models.Q(status__in=("requested", "presented")),
                name="admissions_one_open_advancement_per_member",
            ),
        ]

    def __str__(self):
        return f"{self.member} — {self.get_kind_display()} ({self.get_status_display()})"

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN_STATUSES

    @property
    def advance_role(self) -> str | None:
        """The role this demande advances the member into (None if their
        ``from_role`` has no mapping for this kind)."""
        return self.ADVANCE_ROLE.get(self.kind, {}).get(self.from_role)

    @property
    def step_label(self) -> str:
        """The track-aware name of this formation step. The passage step is a
        **Passage** on the Analyst track and a **Traversée** on the Scholar
        track; the palimpsest is the same word on both. Keyed off ``from_role``
        (snapshotted when the demande opened) so it's stable after advancement."""
        return step_label_for(self.kind, self.from_role)
