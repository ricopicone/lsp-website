"""Notification wrappers for the application (intake) process.

Each adds an in-app bell row and, when the member's preference allows, sends
the existing admissions email (passed as ``email_fn``). Call these instead of
``admissions.emails`` directly.

The ongoing-formation (advancement demande) notifications live in
``formation.notifications``.
"""

from __future__ import annotations

from django.urls import reverse

from notifications.categories import Category
from notifications.dispatch import notify

from . import emails

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
