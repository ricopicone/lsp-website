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

    profile = getattr(user, "profile", None)
    if profile is not None and (profile.role in Profile.DIRECTORY_ROLES or profile.is_lsp_staff):
        return True

    from workgroups.models import Workgroup, WorkgroupMembership

    return WorkgroupMembership.objects.filter(
        user=user,
        end_date__isnull=True,
        workgroup__kind=Workgroup.Kind.COMMITTEE,
    ).exists()
