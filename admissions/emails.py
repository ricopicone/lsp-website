"""Transactional emails for the application (intake) process.

The ongoing-formation (advancement demande) emails live in
``formation.emails``.
"""

from __future__ import annotations

from email.utils import formataddr

from django.conf import settings
from django.core.mail import EmailMessage

from .models import Application


def _applications_from() -> str:
    """From the Applications Coordinator's real mailbox (so From == Reply-To),
    not the generic no-reply. The lacanschool.org domain is verified in SES, so
    any @lacanschool.org sender is allowed."""
    return formataddr(("LSP Admissions", settings.APPLICATIONS_EMAIL))


def _send(*, subject, body, to, reply_to=None, from_email=None):
    from core.email import school_from

    rt = reply_to or settings.SUPPORT_EMAIL
    EmailMessage(
        subject=subject, body=body,
        from_email=from_email or school_from("LSP Admissions"), to=to,
        reply_to=[rt] if isinstance(rt, str) else list(rt),
    ).send(fail_silently=False)


def _render(key, ctx):
    from .models import MessageTemplate
    from .services import render_template

    t = MessageTemplate.get(key)
    return render_template(t.subject, ctx), render_template(t.body, ctx)


def _coordinator_name():
    from availability.emails import applications_coordinator_name
    return applications_coordinator_name()


def send_interview_invitation(user, application: Application) -> None:
    """Invite an available analyst to interview an applicant (To the analyst)."""
    from .models import MessageTemplate

    ctx = {
        "interviewer": user.get_full_name() or user.email,
        "applicant": application.applicant.get_full_name() or application.applicant.email,
        "formation": _formation_label(application.track, application.background),
        "agree_url": _absolute("admissions:analyst_interview", application.pk),
        "applications_coordinator": _coordinator_name(),
    }
    subject, body = _render(MessageTemplate.Key.INVITATION, ctx)
    _send(subject=subject, body=body, to=[user.email],
          reply_to=settings.APPLICATIONS_EMAIL, from_email=_applications_from())


def send_interview_introduction(interview) -> None:
    """Connect the applicant and the interviewer (To both; reply-all reaches
    both so they can arrange a time)."""
    from .models import MessageTemplate

    app = interview.application
    analyst = interview.interviewer
    ctx = {
        "applicant": app.applicant.get_full_name() or app.applicant.email,
        "interviewer": analyst.get_full_name() or analyst.email,
        "applicant_email": app.applicant.email,
        "interviewer_email": analyst.email,
        "applications_coordinator": _coordinator_name(),
    }
    subject, body = _render(MessageTemplate.Key.INTRODUCTION, ctx)
    _send(subject=subject, body=body,
          to=[app.applicant.email, analyst.email],
          reply_to=[app.applicant.email, analyst.email],
          from_email=_applications_from())


def send_interview_reminder(interview) -> None:
    """Weekly reminder to the interviewer to set up and report (To analyst)."""
    from .models import MessageTemplate

    app = interview.application
    analyst = interview.interviewer
    ctx = {
        "interviewer": analyst.get_full_name() or analyst.email,
        "applicant": app.applicant.get_full_name() or app.applicant.email,
        "url": _absolute("admissions:analyst_interview", app.pk),
        "applications_coordinator": _coordinator_name(),
    }
    subject, body = _render(MessageTemplate.Key.INTERVIEW_REMINDER, ctx)
    _send(subject=subject, body=body, to=[analyst.email],
          reply_to=settings.APPLICATIONS_EMAIL, from_email=_applications_from())


def _absolute(name, *args) -> str:
    from django.urls import reverse
    return settings.SITE_BASE_URL.rstrip("/") + reverse(name, args=args)


def _formation_label(track: str, background: str = "") -> str:
    """e.g. 'Analyst formation, Clinical' — track plus background where given."""
    label = Application.Track(track).label
    if background:
        # "Clinical background" -> "Clinical"
        label += f", {Application.Background(background).label.replace(' background', '')}"
    return label


def _guidelines_url(track: str) -> str:
    """The track's Formation Guidelines document (advisor/advisee
    responsibilities) — Scholar for the scholar track, else Analyst. Falls back
    to the documents index if the document isn't found."""
    from documents.models import Document

    label = "Scholar" if track == Application.Track.SCHOLAR else "Analyst"
    doc = Document.objects.filter(
        title__icontains=f"{label} Formation Guidelines"
    ).first()
    return _absolute("documents:detail", doc.slug) if doc else _absolute("documents:index")


def _member_context(member, *, track: str, background: str = "") -> dict:
    """Letter context for someone being admitted, keyed on the person and their
    track rather than on an ``Application`` — so the same acceptance letter
    renders for a direct admission, which has no application row."""
    from availability.emails import applications_coordinator_name
    return {
        "name": member.get_full_name() or member.email,
        "track": Application.Track(track).label,
        "formation": _formation_label(track, background),
        # Pre-sorted to analysts available to advise.
        "availability_url": _absolute("directory_availability") + "?only=advisor",
        "guidelines_url": _guidelines_url(track),
        "documents_url": _absolute("documents:index"),
        "profile_url": _absolute("profile_edit"),
        "mylsp_url": _absolute("formation:formation"),
        "applications_coordinator": applications_coordinator_name(),
    }


def _applicant_context(application: Application) -> dict:
    """``_member_context`` plus the application-only status link."""
    return {
        **_member_context(
            application.applicant,
            track=application.track,
            background=application.background,
        ),
        "status_url": _absolute("admissions:status"),
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


def send_direct_acceptance(member, *, track, background="", note="") -> None:
    """Send the acceptance letter to a member admitted with no site application.

    Deliberately the *same* ``decision_accept`` template the application route
    sends: however someone was admitted, the welcome they read is identical.
    """
    from .models import MessageTemplate
    from .services import render_template

    t = MessageTemplate.get(MessageTemplate.Key.DECISION_ACCEPT)
    note = (note or "").strip()
    ctx = {
        **_member_context(member, track=track, background=background),
        "note": f"{note}\n\n" if note else "",
    }
    _send(
        subject=render_template(t.subject, ctx),
        body=render_template(t.body, ctx),
        to=[member.email],
        reply_to=settings.APPLICATIONS_EMAIL,
        from_email=_applications_from(),
    )
