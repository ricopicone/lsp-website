"""Formation-advancement workflow — the chokepoints for the palimpsest (and,
later, the passage) demande.

Eligibility and the three transitions live here:

* :func:`open_advancement` — a member opens a demande (snapshots their current
  Advisor and role).
* :func:`present_advancement` — the Advisor records a recommendation and marks
  the demande presented to the Meeting of the Analysts (stops the reminders).
* :func:`decide_advancement` — the Meeting approves (advancing the member's role
  through ``accounts.membership.record_membership_change``) or declines.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from accounts.advisor import current_advisor
from accounts.membership import current_academic_year_start, record_membership_change
from accounts.models import Profile

from . import notifications as notify_formation
from .models import Advancement


def kind_for(member) -> str | None:
    """The advancement step a member is eligible to request from their current
    role (palimpsest for Precandidates, passage for Candidates), or None."""
    return Advancement.KIND_FOR_ROLE.get(member.profile.role)


def step_label_for_member(member) -> str | None:
    """The track-aware name of the step ``member`` may currently request
    (Palimpsest / Passage / Traversée), or None if they're not eligible."""
    from .models import step_label_for

    kind = kind_for(member)
    return step_label_for(kind, member.profile.role) if kind else None


def open_advancement_for(member):
    """The member's current open demande, if any."""
    return (
        Advancement.objects.filter(member=member, status__in=Advancement.OPEN_STATUSES)
        .order_by("-requested_at")
        .first()
    )


def can_open_advancement(member) -> bool:
    """A member may open a demande if their role has a next formation step and
    they have no demande already in flight."""
    return kind_for(member) is not None and open_advancement_for(member) is None


@transaction.atomic
def open_advancement(member, *, statement, palimpsest=None):
    """Open a palimpsest/passage demande for ``member``. Snapshots their current
    Advisor and role, and notifies the Advisor that a recommendation is due."""
    kind = kind_for(member)
    if kind is None:
        raise ValueError(f"{member} is not at a role that can advance.")
    advancement = Advancement.objects.create(
        member=member,
        kind=kind,
        from_role=member.profile.role,
        statement=statement,
        palimpsest=palimpsest or "",
        advisor=current_advisor(member),
        status=Advancement.Status.REQUESTED,
        requested_at=timezone.now(),
    )
    notify_formation.advancement_opened(advancement)
    return advancement


@transaction.atomic
def present_advancement(advancement, *, recommendation, presented_on=None, by=None):
    """The Advisor records their recommendation and marks the demande presented
    to the Meeting of the Analysts. Idempotent on the recommendation text."""
    advancement.recommendation = recommendation
    advancement.presented_at = presented_on or timezone.localdate()
    if advancement.status == Advancement.Status.REQUESTED:
        advancement.status = Advancement.Status.PRESENTED
    advancement.save(update_fields=["recommendation", "presented_at", "status", "updated_at"])
    notify_formation.advancement_presented(advancement)
    return advancement


@transaction.atomic
def decide_advancement(advancement, *, approve, by, effective_ay=None, note=""):
    """The Meeting decides. On approval, advance the member's role (effective the
    given AY, default the current one) via ``record_membership_change``; on
    decline, just record the decision. Emails the member either way."""
    if approve:
        target_role = advancement.advance_role
        if target_role is None:
            raise ValueError(
                f"No advancement target for {advancement.from_role} "
                f"({advancement.get_kind_display()})."
            )
        effective_ay = effective_ay or current_academic_year_start()
        record_membership_change(
            advancement.member,
            role=target_role,
            standing=Profile.Standing.ACTIVE,
            effective_ay=effective_ay,
            notes=f"{advancement.get_kind_display()} approved. {note}".strip(),
            by=by,
        )
        advancement.status = Advancement.Status.APPROVED
    else:
        advancement.status = Advancement.Status.DECLINED
    advancement.decided_at = timezone.now()
    advancement.decided_by = by
    advancement.decision_note = note
    advancement.save(
        update_fields=["status", "decided_at", "decided_by", "decision_note", "updated_at"]
    )
    notify_formation.advancement_decision(advancement)
    return advancement


@transaction.atomic
def withdraw_advancement(advancement):
    advancement.status = Advancement.Status.WITHDRAWN
    advancement.save(update_fields=["status", "updated_at"])
    return advancement
