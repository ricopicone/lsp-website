"""Transactional emails for the application process."""

from __future__ import annotations

from email.utils import formataddr

from django.conf import settings
from django.core.mail import EmailMessage

from .models import Advancement, Application


def _applications_from() -> str:
    """From the Applications Coordinator's real mailbox (so From == Reply-To),
    not the generic no-reply. The lacanschool.org domain is verified in SES, so
    any @lacanschool.org sender is allowed."""
    return formataddr(("LSP Admissions", settings.APPLICATIONS_EMAIL))


def _send(*, subject, body, to, reply_to=None, from_email=None):
    from core.email import school_from

    EmailMessage(
        subject=subject, body=body,
        from_email=from_email or school_from("LSP Admissions"), to=to,
        reply_to=[reply_to or settings.SUPPORT_EMAIL],
    ).send(fail_silently=False)


def send_interviewer_nudge(interview, subject: str, body: str) -> None:
    """The Applications Coordinator's reminder to an interviewer whose report is
    still outstanding. From and Reply-To are the coordinator's mailbox."""
    _send(
        subject=subject, body=body,
        to=[interview.interviewer.email],
        reply_to=settings.APPLICATIONS_EMAIL,
        from_email=_applications_from(),
    )


def _absolute(name, *args) -> str:
    from django.urls import reverse
    return settings.SITE_BASE_URL.rstrip("/") + reverse(name, args=args)


def _formation_label(application: Application) -> str:
    """e.g. 'Analyst formation, Clinical' — track plus background where given."""
    label = application.get_track_display()
    if application.background:
        # "Clinical background" -> "Clinical"
        label += f", {application.get_background_display().replace(' background', '')}"
    return label


def _applicant_context(application: Application) -> dict:
    from availability.emails import applications_coordinator_name
    return {
        "name": application.applicant.get_full_name() or application.applicant.email,
        "track": application.get_track_display(),
        "formation": _formation_label(application),
        "availability_url": _absolute("directory_availability"),
        "documents_url": _absolute("documents:index"),
        "profile_url": _absolute("profile_edit"),
        "status_url": _absolute("admissions:status"),
        "applications_coordinator": applications_coordinator_name(),
    }


def send_application_submitted(application: Application) -> None:
    from .models import MessageTemplate
    from .services import render_template

    t = MessageTemplate.get(MessageTemplate.Key.ACKNOWLEDGMENT)
    ctx = _applicant_context(application)
    _send(
        subject=render_template(t.subject, ctx),
        body=render_template(t.body, ctx),
        to=[application.applicant.email],
        reply_to=settings.APPLICATIONS_EMAIL,
        from_email=_applications_from(),
    )


def send_application_decision(application: Application) -> None:
    from .models import MessageTemplate
    from .services import render_template

    accepted = application.status == Application.Status.ACCEPTED
    key = (
        MessageTemplate.Key.DECISION_ACCEPT if accepted
        else MessageTemplate.Key.DECISION_REJECT
    )
    t = MessageTemplate.get(key)
    note = (application.decision_note or "").strip()
    ctx = {**_applicant_context(application), "note": f"{note}\n\n" if note else ""}
    _send(
        subject=render_template(t.subject, ctx),
        body=render_template(t.body, ctx),
        to=[application.applicant.email],
        reply_to=settings.APPLICATIONS_EMAIL,
        from_email=_applications_from(),
    )


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
