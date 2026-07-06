"""Transactional emails for the application (intake) process.

The ongoing-formation (advancement demande) emails live in
``formation.emails``.
"""

from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMessage

from .models import Application


def _send(*, subject, body, to):
    from core.email import school_from

    EmailMessage(
        subject=subject, body=body,
        from_email=school_from("LSP Admissions"), to=to,
        reply_to=[settings.SUPPORT_EMAIL],
    ).send(fail_silently=False)


def send_application_submitted(application: Application) -> None:
    name = application.applicant.get_full_name() or application.applicant.email
    _send(
        subject="We received your LSP application",
        body=(
            f"Dear {name},\n\n"
            f"Thank you for applying to the {application.get_track_display()} at "
            "the Lacanian School of Psychoanalysis. We've received your letter of "
            "intent and CV.\n\n"
            "Next, you'll be put in contact with two Analysts of the School to "
            "schedule two interviews. Your application is then reviewed at the "
            "monthly Meeting of the Analysts, after which we'll be in touch about "
            "the decision.\n\n"
            "You can check your application status any time from your account.\n\n"
            "— The Lacanian School of Psychoanalysis"
        ),
        to=[application.applicant.email],
    )


def send_application_decision(application: Application) -> None:
    name = application.applicant.get_full_name() or application.applicant.email
    if application.status == Application.Status.ACCEPTED:
        body = (
            f"Dear {name},\n\n"
            f"We are glad to welcome you to the {application.get_track_display()} "
            "at the Lacanian School of Psychoanalysis. Your application has been "
            "accepted and you are now admitted as a Precandidate.\n\n"
            "As a next step, please choose an Advisor (an Analyst of the School). "
            "We'll follow up with details.\n\n"
        )
        if application.decision_note:
            body += f"{application.decision_note}\n\n"
        body += "— The Lacanian School of Psychoanalysis"
        subject = "Your LSP application — welcome"
    else:
        body = (
            f"Dear {name},\n\n"
            "Thank you for your interest in the Lacanian School of Psychoanalysis "
            "and for the time you gave to the application process. After review at "
            "the Meeting of the Analysts, we are not able to offer you admission at "
            "this time.\n\n"
        )
        if application.decision_note:
            body += f"{application.decision_note}\n\n"
        body += "— The Lacanian School of Psychoanalysis"
        subject = "Your LSP application"
    _send(subject=subject, body=body, to=[application.applicant.email])
