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
    the applicant.

    A training-sandbox application (the applicant is a persona) invites only the
    persona analysts, keeping the whole exercise within the sandbox cast; a real
    application excludes personas. So the invite never crosses the boundary."""
    from availability.services import interview_status_map

    from .forms import analyst_pool

    pool = analyst_pool().exclude(pk=application.applicant_id)
    if application.applicant.profile.is_persona:
        pool = pool.filter(profile__is_persona=True)
    else:
        pool = pool.exclude(profile__is_persona=True)
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
    created).

    Sandbox containment (defense in depth): a sandbox application only ever
    involves persona analysts, so a mismatch (sandbox app + real analyst, or
    vice versa) is refused — this guards against a real analyst being emailed
    in a training run even if a request bypassed the form."""
    if application.applicant.profile.is_persona != analyst.profile.is_persona:
        raise ValueError("Interviewer/applicant sandbox mismatch — refused.")
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
    try:
        interview, _ = add_interviewer(application, analyst)
    except ValueError:  # sandbox mismatch — not an eligible interviewer here
        return None, "ineligible"
    return interview, "agreed"


def simulate_interviews(application: Application) -> int:
    """Sandbox shortcut: fast-forward the interview stage without impersonating
    each analyst. Persona analysts agree to fill the open slots (sending the
    introductions to the trainee), then their reports are filed, leaving the
    application decision-ready. Only valid for a sandbox application. Returns
    the number of interviews now complete."""
    if not application.applicant.profile.is_persona:
        raise ValueError("Simulation is only for sandbox applications.")

    on_it = set(application.interviews.values_list("interviewer_id", flat=True))
    pool = [u for u in eligible_interviewers(application) if u.pk not in on_it]
    while slots_remaining(application) > 0 and pool:
        add_interviewer(application, pool.pop(0))  # intro email → the trainee

    for interview in application.interviews.all():
        if not interview.is_complete:
            interview.completed_at = timezone.localdate()
            interview.report = (
                "Sandbox — simulated interview report. A thoughtful candidate."
            )
            interview.save(update_fields=["completed_at", "report"])
    return application.interviews.count()


# ---- Admission: the shared chokepoint -----------------------------------


@transaction.atomic
def admit_member(
    member, *, track, formation_background="", effective_ay=None, by,
    tenure_note="", background_note="",
):
    """Admit ``member`` as ``track``'s Precandidate — the membership change plus
    the formation background, and nothing route-specific.

    Shared by both admission routes: acceptance of a site application
    (:func:`accept_application`) and direct admission by the Web Coordinator
    (``admissions.direct_admit``). Keeping one function means the two cannot
    drift — a member admitted either way lands in the same state.

    ``formation_background`` is a ``Profile.FormationBackground`` value, or ""
    to leave the member unreviewed (the Meeting of Analysts determines it
    later). Returns the open ``MembershipTenure``.
    """
    effective_ay = effective_ay or current_academic_year_start()
    tenure = record_membership_change(
        member,
        role=Application.ADMIT_ROLE[track],
        standing=Profile.Standing.ACTIVE,
        effective_ay=effective_ay,
        notes=tenure_note,
        by=by,
    )
    if formation_background:
        from formation.background import set_background

        set_background(member, formation_background, by=by, note=background_note)
    return tenure


@transaction.atomic
def accept_application(application: Application, *, by, effective_ay=None, note=""):
    """Accept an application: admit the applicant as the track's Precandidate
    (active standing) and mark the application accepted. Emails the applicant."""
    background = (
        Profile.FormationBackground.CLINICAL
        if application.background == Application.Background.CLINICAL
        else Profile.FormationBackground.ACADEMIC
    )
    admit_member(
        application.applicant,
        track=application.track,
        formation_background=background,
        effective_ay=effective_ay,
        by=by,
        tenure_note=(
            f"Admitted via application ({application.get_track_display()}). {note}"
        ).strip(),
        background_note="Set at acceptance from the application.",
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


