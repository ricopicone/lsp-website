"""Who may view an advisee's read-only formation record + private advisor notes.

An advisee's *current* advisor (the open ``Advisorship`` row, ``end_date`` null,
matching :func:`accounts.advisor.current_advisor`) may see it, as may staff. The
advisee themselves must never see the advisor notes, so this gate is used only on
the advisor-facing advisee-detail page.
"""

from __future__ import annotations

from accounts.advisor import current_advisor
from accounts.models import Advisorship


def current_advisees(advisor):
    """Users whom ``advisor`` currently advises (open Advisorship rows), mirroring
    the "current" semantics of :func:`accounts.advisor.current_advisor`."""
    return (
        Advisorship.objects.filter(advisor=advisor, end_date__isnull=True)
        .select_related("advisee", "advisee__profile")
        .order_by("advisee__last_name", "advisee__first_name", "advisee__email")
    )


def can_view_advisee(viewer, advisee) -> bool:
    if not getattr(viewer, "is_authenticated", False):
        return False
    if viewer.pk == advisee.pk:
        return False
    if viewer.is_staff:
        return True
    return current_advisor(advisee) == viewer
