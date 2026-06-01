"""Permission helpers for the shared Workgroup layer.

``can_manage_workgroup`` is the single "may this user administer this group"
primitive (roster, settings, archive) reused by every concrete kind.
``is_board`` mirrors ``events.permissions.is_program_committee`` for the Board.
"""

from __future__ import annotations

from .models import WorkgroupMembership


def can_manage_workgroup(user, workgroup) -> bool:
    """Whether ``user`` may manage ``workgroup`` — edit its roster/settings,
    archive it. True for Django staff, any lead-role member (chair, co-chair,
    plus-one, faculty), and Programming Committee members."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_staff:
        return True
    if workgroup.memberships.filter(
        user=user, end_date__isnull=True, role__in=WorkgroupMembership.LEAD_ROLES,
    ).exists():
        return True
    # Lazy import: events imports workgroups, so import here to avoid a cycle.
    from events.permissions import is_program_committee

    return is_program_committee(user)


def is_board(user) -> bool:
    """True if ``user`` is a current member of the Board committee."""
    if not getattr(user, "is_authenticated", False):
        return False
    return WorkgroupMembership.objects.filter(
        user=user, end_date__isnull=True,
        workgroup__committee__slug="board",
    ).exists()
