"""Cartel access checks."""

from __future__ import annotations


def is_cartel_coordinator(user) -> bool:
    """Whether ``user`` may review/approve cartel proposals (CART-4).

    The Cartel Coordinator designation (``Profile.is_cartel_coordinator``);
    Django staff also qualify.
    """
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_staff:
        return True
    profile = getattr(user, "profile", None)
    return bool(profile and profile.is_cartel_coordinator)
