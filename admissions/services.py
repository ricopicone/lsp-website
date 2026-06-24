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
from .models import Application, ApplicationInterview

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


def acknowledge(application: Application) -> None:
    """Send the applicant acknowledgment (bell + email) and stamp it."""
    notify_admissions.application_submitted(application)
    application.acknowledged_at = timezone.now()
    application.save(update_fields=["acknowledged_at"])


def acknowledge_on_submit(application: Application) -> None:
    """On submit, acknowledge automatically unless the coordinator set the
    acknowledgment to review-first (then they send it from the console)."""
    from .models import AdmissionsSettings

    if AdmissionsSettings.load().acknowledgment_mode == AdmissionsSettings.Mode.AUTO:
        acknowledge(application)


# ---- Interviewer staffing: invite → agree → connect ----------------------


def eligible_interviewers(application: Application) -> list:
    """Active Analysts of the School who may be INVITED to interview — those
    Yes or Unknown for Application Interviews (i.e. not explicitly No), minus
    the applicant and disposable personas."""
    from availability.services import interview_status_map

    from .forms import analyst_pool

    pool = (
        analyst_pool()
        .exclude(pk=application.applicant_id)
        .exclude(profile__is_persona=True)
    )
    status = interview_status_map(pool.values_list("pk", flat=True))
    return [u for u in pool if status.get(u.pk, "unknown") != "no"]


def slots_remaining(application: Application) -> int:
    return max(0, Application.INTERVIEWS_NEEDED - application.interviews.count())


@transaction.atomic
def invite_interviewers(application: Application) -> int:
    """Email eligible analysts inviting them to interview; mark the application
    invited and move it into interviews. Returns how many were invited."""
    if application.interviewers_invited_at is None:
        application.interviewers_invited_at = timezone.now()
    if application.status == Application.Status.SUBMITTED:
        application.status = Application.Status.INTERVIEWING
    application.save(update_fields=["interviewers_invited_at", "status"])

    invitees = eligible_interviewers(application)
    for user in invitees:
        notify_admissions.interview_invitation(application, user)
    return len(invitees)


def invite_on_submit(application: Application) -> None:
    """Auto-invite interviewers on submit when the coordinator set it to
    automatic (default is review-first — they press Invite)."""
    from .models import AdmissionsSettings

    if AdmissionsSettings.load().invitation_mode == AdmissionsSettings.Mode.AUTO:
        invite_interviewers(application)


def add_interviewer(application: Application, analyst, *, by=None):
    """Record ``analyst`` as an interviewer (idempotent) and send the
    introduction connecting them with the applicant. Returns (interview,
    created)."""
    interview, created = ApplicationInterview.objects.get_or_create(
        application=application, interviewer=analyst,
        defaults={"agreed_at": timezone.now()},
    )
    if created:
        if application.status == Application.Status.SUBMITTED:
            application.status = Application.Status.INTERVIEWING
            application.save(update_fields=["status"])
        notify_admissions.interview_introduction(interview)
    return interview, created


def agree_to_interview(application: Application, analyst):
    """An analyst opts in from an invitation. Returns (interview, outcome) where
    outcome is 'agreed', 'already' (they were already on it), or 'full'."""
    existing = application.interviews.filter(interviewer=analyst).first()
    if existing:
        return existing, "already"
    if slots_remaining(application) <= 0:
        return None, "full"
    interview, _ = add_interviewer(application, analyst)
    return interview, "agreed"


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


