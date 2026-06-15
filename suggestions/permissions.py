"""Who may submit and who may triage suggestions.

Submission is restricted to the Board (per the meeting that scoped this feature):
the suggestion box is open only to Board members, not the full membership.

Triage reuses the existing site-staff roles rather than minting a new one: the
Web Coordinator and Web Developer are exactly the people who act on site-change
suggestions. Superusers always pass both gates.
"""

from __future__ import annotations

from core.access import has_staff_role
from core.models import StaffRole


def can_submit_suggestion(user) -> bool:
    """Whether ``user`` may file a suggestion — Board members and superusers."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    from workgroups.permissions import is_board

    return is_board(user)


def can_triage_suggestions(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return user.is_superuser or has_staff_role(
        user, StaffRole.WEB_COORDINATOR, StaffRole.WEB_DEVELOPER
    )
