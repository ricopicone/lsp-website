"""Notification wrappers for the admissions / formation pipeline.

Each adds an in-app bell row and, when the member's preference allows, sends
the existing admissions email (passed as ``email_fn``). Call these instead of
``admissions.emails`` directly.
"""

from __future__ import annotations

from django.urls import reverse

from notifications.categories import Category
from notifications.dispatch import notify

from . import emails


def _name(user) -> str:
    return (user.get_full_name() if user else "") or "A member"


# --- Applicant-facing -------------------------------------------------------

def application_submitted(application) -> None:
    notify(
        application.applicant, Category.ADMISSIONS_APPLICATION,
        title="We received your application",
        url=reverse("admissions:status"), target=application,
        email_fn=lambda: emails.send_application_submitted(application),
    )


def application_decision(application) -> None:
    notify(
        application.applicant, Category.ADMISSIONS_DECISION,
        title="A decision on your application",
        url=reverse("admissions:status"), target=application,
        email_fn=lambda: emails.send_application_decision(application),
    )


# --- Interviewer staffing (invite → connect → remind) -----------------------

def interview_invitation(application, user) -> None:
    """Invite an available analyst to interview this applicant (bell + email)."""
    notify(
        user, Category.ADMISSIONS_APPLICATION,
        title="Can you interview an LSP applicant?",
        body="An applicant needs interviewers — let us know if you can take one.",
        url=reverse("admissions:analyst_interview", args=[application.pk]),
        target=application, dedupe=True,
        email_fn=lambda: emails.send_interview_invitation(user, application),
    )


def interview_introduction(interview) -> None:
    """Connect applicant + interviewer so they arrange a time (email to both)."""
    emails.send_interview_introduction(interview)


def interview_reminder(interview) -> None:
    """Weekly nudge to the interviewer to set up / report (email to analyst)."""
    emails.send_interview_reminder(interview)


# --- Member / advisor (advancement demande) ---------------------------------

def advancement_opened(advancement) -> None:
    advisor = advancement.advisor
    if advisor is None:
        return
    notify(
        advisor, Category.ADMISSIONS_ADVANCEMENT,
        title=f"{_name(advancement.member)} opened a demande for your presentation",
        url=reverse("admissions:advise_queue"), target=advancement,
        email_fn=lambda: emails.send_advancement_opened(advancement),
    )


def advancement_reminder(advancement) -> None:
    advisor = advancement.advisor
    if advisor is None:
        return
    notify(
        advisor, Category.ADMISSIONS_ADVANCEMENT,
        title=f"Reminder: present {_name(advancement.member)}'s demande",
        url=reverse("admissions:advise_queue"), target=advancement, dedupe=True,
        email_fn=lambda: emails.send_advancement_reminder(advancement),
    )


def advancement_presented(advancement) -> None:
    notify(
        advancement.member, Category.ADMISSIONS_ADVANCEMENT,
        title="Your demande has been presented",
        url=reverse("admissions:formation"), target=advancement,
        email_fn=lambda: emails.send_advancement_presented(advancement),
    )


def advancement_decision(advancement) -> None:
    notify(
        advancement.member, Category.ADMISSIONS_DECISION,
        title="A decision on your advancement",
        url=reverse("admissions:formation"), target=advancement,
        email_fn=lambda: emails.send_advancement_decision(advancement),
    )
