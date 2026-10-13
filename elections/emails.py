"""Election email (task #813). Each message renders a plain-text template in
the recipient's own timezone. None ever carries the contents of a ballot,
and none goes to a declined nominee: a Board member tells them in person
(bylaws Art. 3 §1)."""

from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.urls import reverse

from core.email import school_from
from payments.emails import _recipient_timezone

SENDER = "LSP Election Administrator"


def _reply_to() -> list[str]:
    from core.models import StaffRole

    role = StaffRole.objects.filter(key=StaffRole.ELECTION_ADMINISTRATOR).first()
    emails = [u.email for u in role.holders.all()] if role else []
    return emails or [settings.SUPPORT_EMAIL]


def tab_link() -> str:
    return f"{settings.SITE_BASE_URL.rstrip('/')}{reverse('formation')}?tab=election"


def _send(template: str, subject: str, user, election, **extra) -> None:
    with _recipient_timezone(user):
        body = render_to_string(f"elections/email/{template}.txt", {
            "recipient": user, "election": election, "url": tab_link(), **extra,
        })
    EmailMessage(
        subject=subject, body=body, from_email=school_from(SENDER),
        to=[user.email], reply_to=_reply_to(),
    ).send(fail_silently=False)


def send_call(user, e):
    _send("call", f"Call for nominations: {e.title}", user, e)


def send_nomination_received(user, e):
    _send("nomination_received", f"We received your nomination: {e.title}", user, e)


def send_candidacy_accepted(user, e):
    _send("candidacy_accepted", f"Your candidacy is on the slate: {e.title}", user, e)


def send_voting_open(user, e):
    _send("voting_open", f"Voting is open: {e.title}", user, e)


def send_reminder(user, e):
    _send("reminder", f"Reminder, please vote: {e.title}", user, e)


def send_ballot_recorded(user, e):
    _send("ballot_recorded", f"Your ballot was recorded: {e.title}", user, e)


def send_results(user, e):
    if e.acclaimed_at:
        from .ballots import candidates
        winners = [n.name for n in candidates(e)]
    else:
        names = (e.count_result or {}).get("names", {})
        winners = [names.get(str(i), "") for i in (e.count_result or {}).get("elected", [])]
    _send("results", f"Results: {e.title}", user, e, winners=winners)
