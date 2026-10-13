"""Who may run an election and who reviews nominations (task #813)."""

from __future__ import annotations

from core.access import has_staff_role
from core.models import StaffRole


def is_election_administrator(user) -> bool:
    """The Election Administrator console gate. Deliberately not the Web
    Coordinator: the role exists to be impartial, and knowing who has voted
    should not come bundled with another office."""
    return bool(getattr(user, "is_authenticated", False)) and (
        user.is_superuser or has_staff_role(user, StaffRole.ELECTION_ADMINISTRATOR)
    )


def can_review_nominations(user) -> bool:
    """The bylaws give candidacy review to the Board (Art. 3 §1)."""
    from committees.permissions import is_on_committee

    return bool(getattr(user, "is_authenticated", False)) and (
        user.is_superuser or is_on_committee(user, "board")
    )
