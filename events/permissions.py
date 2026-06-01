"""Permission helpers for event-level views (PROG-7, PROG-8)."""

from __future__ import annotations

from workgroups.models import WorkgroupMembership


def _is_lsp_staff(user) -> bool:
    from core.access import has_staff_role
    from core.models import StaffRole

    return has_staff_role(user, StaffRole.LSP_STAFF)


def can_edit_event(user, event) -> bool:
    """True if ``user`` may edit ``event`` (PROG-7) or see its faculty surfaces (PROG-8).

    Event-edit rights come from: Django staff, the LSP Staff designation (which
    replaced the former 'lsp-staff' committee), the event's own faculty, or
    Programming Committee membership.
    """
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_staff or _is_lsp_staff(user):
        return True
    if event.is_faculty(user):
        return True
    return WorkgroupMembership.objects.filter(
        user=user,
        end_date__isnull=True,
        workgroup__committee__slug="programming-committee",
    ).exists()


def is_program_committee(user) -> bool:
    """True if ``user`` is a current member of the Programming Committee.

    Used to gate Program preview before publication and the
    Program Committee admin interface.
    """
    if not getattr(user, "is_authenticated", False):
        return False
    return WorkgroupMembership.objects.filter(
        user=user,
        end_date__isnull=True,
        workgroup__committee__slug="programming-committee",
    ).exists()
