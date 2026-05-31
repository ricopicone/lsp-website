"""Cartel access checks."""

from __future__ import annotations


def is_cartel_coordinator(user) -> bool:
    """Whether ``user`` may review/approve cartel proposals (CART-4).

    The Cartel Coordinator staff role (``core.StaffRole`` key
    ``cartel_coordinator``); Django staff also qualify.
    """
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_staff:
        return True
    from core.access import has_staff_role
    from core.models import StaffRole

    return has_staff_role(user, StaffRole.CARTEL_COORDINATOR)
