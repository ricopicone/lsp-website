"""Transactional emails for the application process."""

from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMessage

from .models import Advancement, Application


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


# ---------------------------------------------------------------------------
# Advancement (palimpsest / passage) demande notifications
# ---------------------------------------------------------------------------

def _member_name(advancement: Advancement) -> str:
    m = advancement.member
    return m.get_full_name() or m.email


def send_advancement_opened(advancement: Advancement) -> None:
    """Notify the Advisor that a demande awaits their recommendation."""
    advisor = advancement.advisor
    if advisor is None:
        return  # no advisor on file yet; the member is prompted to choose one
    step = advancement.get_kind_display()
    _send(
        subject=f"A {step} demande needs your recommendation",
        body=(
            f"Dear {advisor.get_full_name() or advisor.email},\n\n"
            f"{_member_name(advancement)}, whom you advise, has opened a "
            f"{step} demande.\n\n"
            "As their Advisor, you are asked to write a recommendation and "
            "**present the demande to the Meeting of the Analysts**. Once you "
            "have presented it, record that from your account so we stop "
            "reminding you.\n\n"
            "— The Lacanian School of Psychoanalysis"
        ),
        to=[advisor.email],
    )


def send_advancement_reminder(advancement: Advancement) -> None:
    """Nudge the Advisor of a still-unpresented demande."""
    advisor = advancement.advisor
    if advisor is None:
        return
    step = advancement.get_kind_display()
    _send(
        subject=f"Reminder: present {_member_name(advancement)}'s {step} demande",
        body=(
            f"Dear {advisor.get_full_name() or advisor.email},\n\n"
            f"{_member_name(advancement)}'s {step} demande is still awaiting "
            "your recommendation and presentation to the Meeting of the "
            "Analysts. When you have presented it, record that from your "
            "account.\n\n"
            "— The Lacanian School of Psychoanalysis"
        ),
        to=[advisor.email],
    )


def send_advancement_presented(advancement: Advancement) -> None:
    """Let the member know their demande has been presented to the Meeting."""
    _send(
        subject="Your formation demande has been presented",
        body=(
            f"Dear {_member_name(advancement)},\n\n"
            f"Your {advancement.get_kind_display()} demande has been presented "
            "to the Meeting of the Analysts by your Advisor. The Meeting will "
            "consider it and we'll be in touch about the decision.\n\n"
            "— The Lacanian School of Psychoanalysis"
        ),
        to=[advancement.member.email],
    )


def send_advancement_decision(advancement: Advancement) -> None:
    name = _member_name(advancement)
    if advancement.status == Advancement.Status.APPROVED:
        new_role = dict(advancement.member.profile.Role.choices).get(
            advancement.advance_role, "the next step"
        )
        body = (
            f"Dear {name},\n\n"
            f"The Meeting of the Analysts has approved your "
            f"{advancement.get_kind_display()} demande. You now advance to "
            f"{new_role}.\n\n"
        )
        if advancement.decision_note:
            body += f"{advancement.decision_note}\n\n"
        body += "— The Lacanian School of Psychoanalysis"
        subject = "Your formation demande — approved"
    else:
        body = (
            f"Dear {name},\n\n"
            f"After consideration at the Meeting of the Analysts, your "
            f"{advancement.get_kind_display()} demande was not approved at this "
            "time. Your Advisor can discuss next steps with you.\n\n"
        )
        if advancement.decision_note:
            body += f"{advancement.decision_note}\n\n"
        body += "— The Lacanian School of Psychoanalysis"
        subject = "Your formation demande"
    _send(subject=subject, body=body, to=[advancement.member.email])
