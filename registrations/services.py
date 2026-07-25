"""Shared registration staff operations (REG-14).

One home for side-effect chains used by both the Django admin and the
Registration Admin console, so they cannot drift.
"""

from __future__ import annotations

from django.utils import timezone

from payments import notifications as notify_payments

from .models import Registration


def comp_registration(reg, by, *, via: str = "admin") -> tuple[bool, bool]:
    """Comp an awaiting-payment registration (REG-14).

    Flips to COMPED, appends the dated ``staff_notes`` audit line, mints the
    comped ledger charge, and sends the confirmation (with access info).
    Returns ``(comped, email_ok)`` — ``comped`` False when the row wasn't in
    ``AWAITING_PAYMENT``; ``email_ok`` False when the status flip succeeded
    but the notification raised.
    """
    if reg.status != Registration.Status.AWAITING_PAYMENT:
        return False, True
    reg.status = Registration.Status.COMPED
    reg.staff_notes = (reg.staff_notes or "") + (
        f"\n[{timezone.now().date().isoformat()}] Comped by {by.email} via {via}."
    )
    reg.save(update_fields=("status", "staff_notes"))
    from payments.charges import mint_comped_charge
    mint_comped_charge(reg)
    try:
        notify_payments.registration_confirmed(reg)
    except Exception:
        return True, False
    return True, True
