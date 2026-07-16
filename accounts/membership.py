"""Membership administration — the Board's record-keeping for role and standing
changes across the school.

``record_membership_change`` is the single chokepoint every change type (admit,
advance, leave, return, resign, emeritus) routes through. It keeps three things
in sync: the member's open :class:`~accounts.models.MembershipTenure` (closed at
the change), a new open tenure (the new role + standing), and the live
``Profile.role`` / ``Profile.standing`` caches.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .models import MembershipTenure, Source


def current_academic_year_start(on_date=None) -> int:
    """AY start year for ``on_date`` (default today): the AY runs Sep 1 – Aug 31,
    so Jan–Aug belongs to the previous calendar year's AY."""
    today = on_date or timezone.localdate()
    return today.year if today.month >= 9 else today.year - 1


def academic_year_label(year: int) -> str:
    """'AY 2019–2020' for a start year."""
    return f"AY {year}–{year + 1}"


def academic_year_choices(start: int = 1992) -> list[tuple[int, str]]:
    """Academic years (start year, label) from ``start`` to the current AY, newest
    first — for the survey's join-year and formation-milestone selectors. The
    range covers the School's full history; financial periods are seeded only
    from 2015 (see ``seed_historical_periods``)."""
    current = current_academic_year_start()
    return [(y, academic_year_label(y)) for y in range(current, start - 1, -1)]


GATED_ROLES = frozenset({"analyst", "scholar"})

FIX_PATH = ("Resolve on the member's treasurer account page (record payment, "
            "adjust, waive, or void), then retry.")


def validate_role_transition(user, new_role) -> None:
    """Refuse promotion out of training while tuition is unsettled.

    Necessary but insufficient — the Passage/Traversée decision stays with
    the Meeting of Analysts. No override flag: the ledger is the override
    (spec 2026-07-16).
    """
    from django.core.exceptions import ValidationError

    from accounts.models import Profile

    if new_role not in GATED_ROLES:
        return
    profile = getattr(user, "profile", None)
    if profile is None or profile.role not in Profile.IN_TRAINING_ROLES:
        return  # not a promotion out of training (bootstrap/external records)
    from payments.ledger import tuition_clearance

    reasons = tuition_clearance(user)
    if reasons:
        raise ValidationError(reasons + [FIX_PATH])


@transaction.atomic
def record_membership_change(
    member, *, role, standing, effective_ay, notes="", by=None,
    source=Source.STAFF,
):
    """Record a membership change effective ``effective_ay`` (an AY start year).

    Closes the member's open tenure (ending it the AY before the change) and
    opens a new one with the new role + standing, then updates the live Profile.
    If the change is effective in the *same or an earlier* AY than the current
    open tenure's start, the open tenure is corrected in place instead (so a
    same-year correction doesn't create a zero-length stub). Returns the
    resulting open ``MembershipTenure``.
    """
    validate_role_transition(member, role)
    if by is not None:
        stamp = f"[{timezone.localdate()} by {by.email}]"
        notes = f"{stamp} {notes}".strip() if notes else stamp

    open_tenure = MembershipTenure.open_for(member)

    if open_tenure is not None and effective_ay <= open_tenure.start_ay:
        # Correct the current tenure in place (same-year or backdated fix).
        open_tenure.role = role
        open_tenure.standing = standing
        open_tenure.start_ay = effective_ay
        open_tenure.source = source
        if notes:
            open_tenure.notes = (
                (open_tenure.notes + "\n" + notes).strip() if open_tenure.notes else notes
            )
        open_tenure.save(update_fields=["role", "standing", "start_ay", "source", "notes"])
        tenure = open_tenure
    else:
        if open_tenure is not None:
            open_tenure.end_ay = effective_ay - 1
            open_tenure.save(update_fields=["end_ay"])
        tenure = MembershipTenure.objects.create(
            user=member, role=role, standing=standing, start_ay=effective_ay,
            source=source, notes=notes,
        )

    profile = member.profile
    profile.role = role
    profile.standing = standing
    profile.save(update_fields=["role", "standing"])
    return tenure
