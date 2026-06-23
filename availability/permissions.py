"""Who may run the analyst-availability console.

Gated to the Applications Coordinator staff role (plus superusers) —
deliberately *not* generic ``is_staff``, mirroring the Referral Coordinator.
The availability data is members-internal and the coordinator is a specific
appointed person (the Applications Coordinator).
"""

from __future__ import annotations

from core.access import has_staff_role
from core.models import StaffRole


def can_manage_availability(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return user.is_superuser or has_staff_role(
        user, StaffRole.APPLICATIONS_COORDINATOR
    )
