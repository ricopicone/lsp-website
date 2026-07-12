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
    # The President / Vice-President are school officers who govern the standing
    # bodies — one appointment carries authority across them (and the school).
    if (has_staff_role(user, StaffRole.PRESIDENT)
            or has_staff_role(user, StaffRole.VICE_PRESIDENT)):
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


def workgroup_has_leads(workgroup) -> bool:
    """Whether any currently-serving member holds a leadership role (chair,
    co-chair, faculty, organizer). False for leaderless groups like cartels
    (a plus-one is deliberately not a lead)."""
    return workgroup.memberships.serving().filter(
        role__in=WorkgroupMembership.LEAD_ROLES
    ).exists()


def can_register_decision(user, workgroup) -> bool:
    """Who may record a decision in the group's register.

    Leader-led groups (a chair / co-chair / faculty / organizer serves): those
    leaders plus managers (LSP staff / PC / Board). Leaderless groups — e.g.
    cartels, where the plus-one isn't a lead — let any active member record."""
    if not getattr(user, "is_authenticated", False):
        return False
    if can_manage_workgroup(user, workgroup):
        return True
    return not workgroup_has_leads(workgroup) and workgroup.is_member(user)


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


def _meeting_of_analysts_workgroup_id():
    """The Meeting of Analysts' backing workgroup id, or None."""
    from committees.models import Committee

    committee = (
        Committee.objects.filter(slug="meeting-of-analysts")
        .only("workgroup_id")
        .first()
    )
    return committee.workgroup_id if committee else None


def meeting_of_analysts_members():
    """Every user in the Meeting of the Analysts: all active Analysts
    (role-derived) plus any hand-added roster members, deduped.

    Personas (training-sandbox accounts) are excluded — the same rule
    :meth:`Workgroup.active_members` applies, so a real fan-out (email/bell)
    never reaches a trainee's persona."""
    from django.db.models import Q

    from accounts.models import Profile, User

    analyst_ids = list(
        User.objects.filter(
            profile__role=Profile.Role.ANALYST, is_active=True,
            profile__is_persona=False,
        ).values_list("pk", flat=True)
    )
    roster_ids = []
    wg_id = _meeting_of_analysts_workgroup_id()
    if wg_id:
        from .models import Workgroup

        wg = Workgroup.objects.filter(pk=wg_id).first()
        if wg:
            roster_ids = [m.user_id for m in wg.active_members()]
    return User.objects.filter(Q(pk__in=analyst_ids) | Q(pk__in=roster_ids)).distinct()


def is_applications_coordinator(user) -> bool:
    """True if ``user`` holds the Applications Coordinator role on the Meeting of
    Analysts workgroup — the officer who facilitates admissions (intake,
    staffing interviewers, chasing reports) for the Meeting, which keeps the
    decision. Superusers included."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    from .models import WorkgroupMembership

    wg_id = _meeting_of_analysts_workgroup_id()
    if wg_id is None:
        return False
    return (
        WorkgroupMembership.objects.serving()
        .filter(
            workgroup_id=wg_id,
            user=user,
            role=WorkgroupMembership.Role.APPLICATIONS_COORDINATOR,
        )
        .exists()
    )
