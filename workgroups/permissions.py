"""Permission helpers for the shared Workgroup layer.

``can_manage_workgroup`` is the single "may this user administer this group"
primitive (roster, settings, archive) reused by every concrete kind.
``is_board`` mirrors ``events.permissions.is_program_committee`` for the Board.
"""

from __future__ import annotations

from .models import WorkgroupMembership


def can_manage_workgroup(user, workgroup) -> bool:
    """Whether ``user`` may manage ``workgroup`` — edit its roster/settings,
    archive it. True for a Django superuser, LSP Staff, Programming Committee
    members, and any lead-role member (chair, co-chair, plus-one, faculty,
    organizer). The single source of truth used across the group surfaces."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    # Lazy imports: events/core import workgroups, so import here to avoid a cycle.
    from core.access import has_staff_role
    from core.models import StaffRole

    if has_staff_role(user, StaffRole.LSP_STAFF):
        return True
    from events.permissions import is_program_committee

    if is_program_committee(user):
        return True
    if workgroup.memberships.serving().filter(
        user=user, role__in=WorkgroupMembership.LEAD_ROLES,
    ).exists():
        return True
    # The Board oversees the school's standing bodies (G4 roster authority).
    return is_board(user)


def is_board(user) -> bool:
    """True if ``user`` is a current member of the Board committee."""
    if not getattr(user, "is_authenticated", False):
        return False
    return WorkgroupMembership.objects.serving().filter(
        user=user, workgroup__committee__slug="board",
    ).exists()


def is_meeting_of_analysts(user) -> bool:
    """True if ``user`` belongs to the Meeting of Analysts — the body that owns
    the formation pipeline (admissions, palimpsest, passage). Membership is
    role-derived (every active Analyst, via the workgroup's ``auto_member_role``)
    plus any explicitly-added roster rows, so this routes through
    :meth:`Workgroup.is_member` rather than the stored-rows query."""
    if not getattr(user, "is_authenticated", False):
        return False
    from committees.models import Committee

    committee = (
        Committee.objects.filter(slug="meeting-of-analysts")
        .select_related("workgroup")
        .first()
    )
    return bool(
        committee and committee.workgroup_id and committee.workgroup.is_member(user)
    )
