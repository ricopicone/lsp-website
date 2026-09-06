"""How an event is joined, said once (task #716).

Stephanie Swales' registrants emailed her asking for a meeting link the day
before her event, because nothing had told them the Join button on the event
page *is* the link. Three surfaces need to say how an event is joined — the
confirmation email, the reminder faculty or staff send by hand, and the send
page's preview — and each re-deriving it from ``format`` / ``online_venue`` /
``access_info`` is how the confirmation email came to mail in-person
registrants a video-room link (task #624). So the venue is described here, in
one place, and every email renders the same block.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone


def _absolute(path: str) -> str:
    return settings.SITE_BASE_URL.rstrip("/") + path


@dataclass(frozen=True)
class JoiningDetails:
    """What a registrant needs to know to show up.

    ``kind`` is one of ``insite`` (the site's own video room), ``external``
    (Zoom or another service; the link is in ``access_info``), ``in_person``
    (the venue is in ``access_info``), or ``online_unknown`` (an online event
    whose venue would be the site's room but video is switched off site-wide —
    nothing to promise yet).
    """

    kind: str
    event_url: str
    system_check_url: str
    access_info: str
    hybrid: bool
    next_start_at: object  # datetime | None

    @property
    def insite(self) -> bool:
        return self.kind == "insite"


def joining_details(event) -> JoiningDetails:
    from video.services import daily_enabled

    from .models import Event

    if event.format == Event.Format.IN_PERSON:
        kind = "in_person"
    elif event.online_venue == Event.OnlineVenue.EXTERNAL:
        kind = "external"
    elif daily_enabled():
        kind = "insite"
    else:
        kind = "online_unknown"
    nxt = event.next_session()
    next_start_at = nxt.start_at if nxt is not None else None
    return JoiningDetails(
        kind=kind,
        event_url=_absolute(reverse("events:detail", args=[event.slug])),
        system_check_url=_absolute(reverse("video:system_check")),
        access_info=(event.access_info or "").strip(),
        hybrid=event.format == Event.Format.HYBRID,
        next_start_at=next_start_at,
    )


def joining_recipients(event):
    """Registrations that have access to the joining details: paid or comped.

    A registration on a payment plan reads PAID (the plan grants access), so it
    is included; awaiting-payment, pending, declined, cancelled and refunded are
    not — they would be sent a door they can't open.
    """
    from registrations.models import Registration

    return (
        event.registrations
        .filter(status__in=(Registration.Status.PAID, Registration.Status.COMPED))
        .filter(user__is_active=True)
        .select_related("user")
        .order_by("user__last_name", "user__first_name", "user__email")
    )


def recipient_addresses(event) -> list[str]:
    """Deduplicated email addresses of the recipients, for the copy box."""
    seen: set[str] = set()
    out: list[str] = []
    for reg in joining_recipients(event):
        addr = reg.user.email
        if addr.lower() not in seen:
            seen.add(addr.lower())
            out.append(addr)
    return out


def default_message(event) -> str:
    """The editable part of the email, prefilled. Faculty rewrite it freely."""
    return (
        f"A reminder about how to join \"{event.title}\". "
        "You don't need a separate meeting link. The details are below. "
        "Looking forward to seeing you there."
    )


def render_joining_email(
    event, *, recipient, message: str, signature: str, sender_name: str = ""
) -> str:
    """The plain-text body for one recipient, in their timezone."""
    from payments.emails import _recipient_timezone

    with _recipient_timezone(recipient):
        return render_to_string(
            "events/email/joining_instructions.txt",
            {
                "event": event,
                "recipient": recipient,
                "message": message.strip(),
                "joining": joining_details(event),
                "signature": signature,
                "sender_name": sender_name,
                "support_email": settings.SUPPORT_EMAIL,
                "site_base_url": settings.SITE_BASE_URL,
            },
        )


def signature_for(event, user, sign_as: str) -> tuple[str, str]:
    """(signature line, reply-to address) for a send.

    ``sign_as`` is ``"me"`` (the sender's name, replies go to them) or
    ``"school"`` (the School's name, replies go to the support mailbox). Who
    the message is *from* was the open question in the task: faculty want it in
    their own voice, staff want something generic, and a choice on the page
    keeps that a human decision rather than a rule.
    """
    if sign_as == "me":
        name = user.get_full_name().strip() or user.email
        return name, user.email
    return "Lacanian School of Psychoanalysis", settings.SUPPORT_EMAIL


def send_joining_instructions(event, *, sender, message: str, sign_as: str) -> int:
    """Email every recipient the joining details, pacing the batch, and record
    the send. Returns how many were sent."""
    from core.email import school_from
    from payments.sending import ThrottledSender

    from .models import JoiningInstructionsSend

    signature, reply_to = signature_for(event, sender, sign_as)
    subject = f"How to join: {event.title}"
    throttled = ThrottledSender()
    sent = 0

    def _one(reg):
        body = render_joining_email(
            event, recipient=reg.user, message=message, signature=signature,
            sender_name=sender.get_full_name().strip(),
        )
        msg = EmailMultiAlternatives(
            subject=subject,
            body=body,
            from_email=school_from("Lacanian School of Psychoanalysis"),
            to=[reg.user.email],
            reply_to=[reply_to],
        )
        msg.send(fail_silently=False)

    for reg in joining_recipients(event):
        throttled.send(_one, reg)
        sent += 1

    JoiningInstructionsSend.objects.create(
        event=event, sent_by=sender, sent_at=timezone.now(),
        recipient_count=sent, message=message.strip(), sign_as=sign_as,
    )
    return sent
