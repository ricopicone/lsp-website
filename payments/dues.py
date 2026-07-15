"""Dues-lifecycle helpers (REG-12).

Pure-function answer to *is this user obligated to pay dues?* (depends on
their role) — the definition of who a dues charge gets minted for
(:func:`payments.charges.sync_dues_charges`). *Has this user paid?* is no
longer answered here — it's a read of the unified ledger
(``payments.ledger.member_account(user)["dues_state"]``, task #439).

The model entities (``DuesPeriod``, ``DuesReminder``) live in
:mod:`payments.models`; this module is the read-side seam other apps
(landing, registration, treasurer dashboard) import.
"""

from __future__ import annotations

from django.conf import settings


def is_dues_obligated(user) -> bool:
    """True when the user owes annual dues — a dues-obligated *role* held with
    *active* standing. On-leave / resigned / emeritus members are exempt."""
    if not user.is_authenticated:
        return False
    profile = getattr(user, "profile", None)
    if profile is None or profile.is_persona:
        return False  # personas are test accounts — never financially obligated
    from accounts.models import Profile
    if profile.standing != Profile.Standing.ACTIVE:
        return False  # on leave / resigned / emeritus → not obligated
    return profile.role in set(settings.DUES_OBLIGATED_ROLES)


def obligated_users_qs():
    """Queryset of users currently obligated to pay dues: active account,
    non-persona, ACTIVE standing, in a dues-obligated role. The single
    definition the treasurer dashboard's counts/lists build on."""
    from accounts.models import Profile, User
    return User.objects.filter(
        is_active=True,
        profile__is_persona=False,
        profile__standing=Profile.Standing.ACTIVE,
        profile__role__in=list(settings.DUES_OBLIGATED_ROLES),
    )


def has_dues_payment_for(user, period) -> bool:
    """Double-payment guard for the member-facing /dues/ page: has this
    member already made a SUCCEEDED dues payment for this period? This is
    deliberately NOT the dues *status* source — the unified ledger
    (payments.ledger) owns status; this only prevents paying twice."""
    if period is None or not user.is_authenticated:
        return False
    from .models import Payment
    return Payment.objects.filter(
        user=user, payment_type=Payment.Type.DUES,
        dues_period=period, status=Payment.Status.SUCCEEDED,
    ).exists()
