"""Application workflow side-effects — the chokepoints for accept / reject.

Acceptance routes admission through ``accounts.membership.record_membership_change``
so the new Precandidate gets the same role-timeline treatment as any Board
membership change.
"""

from __future__ import annotations

import re

from django.db import transaction
from django.utils import timezone

from accounts.membership import current_academic_year_start, record_membership_change
from accounts.models import Profile

from . import notifications as notify_admissions
from .models import Application

_TOKEN = re.compile(r"\{(\w+)\}")


def render_template(text: str, context: dict) -> str:
    """Substitute ``{token}`` placeholders for keys present in ``context``.

    Unknown tokens (and any other braces) are left untouched, so a hand-edited
    coordinator message can never crash a send. Mirrors the referrals helper.
    """
    return _TOKEN.sub(
        lambda m: str(context[m.group(1)]) if m.group(1) in context else m.group(0),
        text,
    )


@transaction.atomic
def accept_application(application: Application, *, by, effective_ay=None, note=""):
    """Accept an application: admit the applicant as the track's Precandidate
    (active standing) and mark the application accepted. Emails the applicant."""
    effective_ay = effective_ay or current_academic_year_start()
    record_membership_change(
        application.applicant,
        role=application.admit_role,
        standing=Profile.Standing.ACTIVE,
        effective_ay=effective_ay,
        notes=f"Admitted via application ({application.get_track_display()}). {note}".strip(),
        by=by,
    )
    application.status = Application.Status.ACCEPTED
    application.decided_at = timezone.now()
    application.decided_by = by
    application.decision_note = note
    application.save(update_fields=["status", "decided_at", "decided_by", "decision_note"])
    notify_admissions.application_decision(application)
    return application


@transaction.atomic
def reject_application(application: Application, *, by, note=""):
    """Decline an application and email the applicant."""
    application.status = Application.Status.REJECTED
    application.decided_at = timezone.now()
    application.decided_by = by
    application.decision_note = note
    application.save(update_fields=["status", "decided_at", "decided_by", "decision_note"])
    notify_admissions.application_decision(application)
    return application


