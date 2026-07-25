"""Member lifecycle side-effects for terminal/non-member states (task #451).

Standing changes (retired/resigned/removed) and the orthogonal ``deceased_on``
date carry consequences beyond the Profile row: login on/off, waiving open
charges, and dropping the member from the referral pool. This module is the one
place those side-effects are orchestrated, so every entry point (Board admin,
Django admin action, scripts) behaves the same.

Imports of ``payments`` and ``referrals`` stay lazy to avoid import cycles
(accounts is a foundation app).
"""

from __future__ import annotations

from django.db import transaction

from .models import Profile


def sync_referral_listing(member) -> None:
    """Deactivate the member's referral listing when they are no longer taking
    new analysands (retired / resigned / removed / deceased). Reinstatement does
    NOT auto-reactivate it — the member re-opts via the profile editor."""
    from referrals.models import ReferralListMember

    profile = getattr(member, "profile", None)
    if profile is None:
        return
    excluded = (
        profile.standing in Profile.REFERRAL_EXCLUDED_STANDINGS
        or profile.is_deceased
    )
    if excluded:
        ReferralListMember.objects.filter(user=member, is_active=True).update(
            is_active=False,
        )


@transaction.atomic
def set_deceased(member, deceased_on, *, by=None) -> None:
    """Mark ``member`` deceased: record the date (disables login via
    Profile.save), auto-waive all open charges, and drop them from referrals."""
    from payments.charges import waive_open_charges

    profile = member.profile
    profile.deceased_on = deceased_on
    profile.save(update_fields=["deceased_on"])  # syncs user.is_active = False
    waive_open_charges(member, reason="Waived — member deceased", by=by)
    sync_referral_listing(member)


@transaction.atomic
def clear_deceased(member, *, by=None) -> None:
    """Reverse a deceased mark: clear the date and re-enable login. Does NOT
    un-waive charges or re-list referrals (those were deliberate actions)."""
    profile = member.profile
    profile.deceased_on = None
    profile.save(update_fields=["deceased_on"])  # syncs user.is_active = True
