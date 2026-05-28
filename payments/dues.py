"""Dues-lifecycle helpers (REG-12).

Pure-function answers to:
- *Is this user obligated to pay dues?* (depends on their role)
- *Has this user paid for the current dues period?*

The model entities (``DuesPeriod``, ``DuesReminder``) live in
:mod:`payments.models`; this module is the read-side seam other apps
(landing, registration, treasurer dashboard) import.
"""

from __future__ import annotations

from django.conf import settings


def is_dues_obligated(user) -> bool:
    """True when the user's role makes them owe annual dues."""
    if not user.is_authenticated:
        return False
    profile = getattr(user, "profile", None)
    if profile is None:
        return False
    return profile.role in set(settings.DUES_OBLIGATED_ROLES)


def user_paid_for_period(user, period) -> bool:
    """True when ``user`` has a SUCCEEDED dues Payment for ``period``."""
    if period is None or not user.is_authenticated:
        return False
    from .models import Payment  # avoid circular import
    return Payment.objects.filter(
        user=user,
        payment_type=Payment.Type.DUES,
        dues_period=period,
        status=Payment.Status.SUCCEEDED,
    ).exists()
