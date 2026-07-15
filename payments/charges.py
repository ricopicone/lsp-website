"""Charge minting (task #439).

Idempotent syncs that materialize obligation rows. Two hard rules, both from
the design spec:

- A sync only manages rows it minted; it NEVER modifies a row a treasurer has
  touched (``staff_adjusted=True``). Disagreements surface via
  :func:`tuition_charge_conflicts` on the Reconcile tab instead of clobbering.
- Every automated path keeps a manual override (do-not-over-automate) —
  add/adjust/waive/void actions live on the treasurer member page.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from accounts.models import Source

from .models import Charge

logger = logging.getLogger(__name__)


def sync_dues_charges(period) -> int:
    """Mint one OPEN dues charge per obligated member for ``period``.

    Refuses future periods (rollover maintains current+next AY — next year's
    members must not show as owing early). Returns the number created.
    """
    from .dues import obligated_users_qs

    today = timezone.now().date()
    if period.start_date > today:
        return 0
    have = set(
        Charge.objects.filter(
            category=Charge.Category.DUES, dues_period=period,
        )
        .exclude(status=Charge.Status.VOID)
        .values_list("user_id", flat=True)
    )
    created = 0
    for user in obligated_users_qs().select_related("profile"):
        if user.id in have:
            continue
        amount = period.amount_for_role(user.profile.role)
        if amount is None:
            continue
        Charge.objects.create(
            user=user,
            category=Charge.Category.DUES,
            amount=amount,
            effective_date=period.start_date,
            dues_period=period,
            source=Source.VERIFIED,
            notes=f"[{today}] Minted from the {period.name} dues tier table.",
        )
        created += 1
    return created
