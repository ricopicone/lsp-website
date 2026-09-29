"""Shared, app-neutral access checks.

Lives in ``accounts`` so apps both "above" (parletre, workgroups) and the
foundation can share one definition without an upward dependency.

``is_lsp_member`` is the canonical "is this user a member of the school?"
gate — the same notion Parlêtre's board-wide gate encodes
(``parletre.permissions.is_member``). For now the two are kept in sync by
hand; the Stage-4 committee fold-in (see ``docs/design-workgroups.md``) is the
natural point to consolidate Parlêtre onto this one.
"""

from __future__ import annotations


def is_lsp_member(user) -> bool:
    """Whether ``user`` counts as an LSP member.

    True for Django staff, anyone holding a directory (member) role, anyone
    with the LSP Staff designation, and anyone on an active committee (Board /
    PC carried under a non-member role still belong — read via the committee's
    workgroup roster after the Stage-4 fold-in).
    """
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_staff:
        return True

    from accounts.models import Profile
    from core.access import has_staff_role
    from core.models import StaffRole

    profile = getattr(user, "profile", None)
    if (
        profile is not None
        and profile.role in Profile.DIRECTORY_ROLES
        and profile.standing not in Profile.NON_MEMBER_STANDINGS
    ):
        return True
    if has_staff_role(user, StaffRole.LSP_STAFF):
        return True

    from workgroups.models import Workgroup, WorkgroupMembership

    return WorkgroupMembership.objects.serving().filter(
        user=user,
        workgroup__kind=Workgroup.Kind.COMMITTEE,
    ).exists()


def lsp_members():
    """Active users for whom :func:`is_lsp_member` is true, as a queryset — the
    whole School, for mail addressed to every member (task #756).

    Mirrors the predicate clause for clause, and a test holds the two to the
    same answer, so who may enter a gathering and who is told about it cannot
    drift. Training-sandbox personas are left out: they are not people.
    """
    from django.db.models import Q

    from accounts.models import Profile, User
    from core.models import StaffRole
    from workgroups.models import Workgroup, serving_membership_q

    committee_ids = (
        Workgroup.objects.filter(kind=Workgroup.Kind.COMMITTEE).values("pk")
    )
    return (
        User.objects.filter(is_active=True)
        .filter(
            Q(is_staff=True)
            | (
                Q(profile__role__in=Profile.DIRECTORY_ROLES)
                & ~Q(profile__standing__in=Profile.NON_MEMBER_STANDINGS)
            )
            | Q(staff_roles__key=StaffRole.LSP_STAFF)
            | (
                Q(workgroup_memberships__workgroup__in=committee_ids)
                & serving_membership_q("workgroup_memberships__")
            )
        )
        .exclude(profile__is_persona=True)
        .distinct()
    )
