"""Permission helpers for event-level views (PROG-7, PROG-8)."""

from __future__ import annotations

from committees.models import CommitteeMembership

# Membership in these committees confers event-edit rights across all events.
EDITOR_COMMITTEE_SLUGS = ("programming-committee", "lsp-staff")


def can_edit_event(user, event) -> bool:
    """True if ``user`` may edit ``event`` (PROG-7) or see its faculty surfaces (PROG-8)."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_staff:
        return True
    if event.faculty.filter(pk=user.pk).exists():
        return True
    return CommitteeMembership.objects.filter(
        user=user,
        committee__slug__in=EDITOR_COMMITTEE_SLUGS,
        end_date__isnull=True,
    ).exists()
