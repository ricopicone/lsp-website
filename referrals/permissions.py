"""Who may run the referral workflow.

Requests carry sensitive personal disclosures, so the surface is gated to
the Referral Coordinator staff role (plus superusers) — deliberately *not*
``is_staff`` like most admin-tools panels.
"""

from __future__ import annotations

from core.access import has_staff_role
from core.models import StaffRole


def can_coordinate_referrals(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return user.is_superuser or has_staff_role(user, StaffRole.REFERRAL_COORDINATOR)
