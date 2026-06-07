"""Who may triage suggestions.

Reuses the existing site-staff roles rather than minting a new one: the Web
Coordinator and Web Developer are exactly the people who act on site-change
suggestions. Superusers always pass.
"""

from __future__ import annotations

from core.access import has_staff_role
from core.models import StaffRole


def can_triage_suggestions(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return user.is_superuser or has_staff_role(
        user, StaffRole.WEB_COORDINATOR, StaffRole.WEB_DEVELOPER
    )
