"""External-speaker invitation: provision-or-link a login, mint a token, send
the invitation email (task #463). Kept separate from the event views so the
provisioning logic is testable in isolation."""
from __future__ import annotations

import datetime as _dt

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, User

from .models import Speaker, SpeakerInvitation

#: Floor for an invitation's life. "The day after the event" alone would hand
#: someone invited on the morning of a same-day event a window of hours, and
#: someone invited *after* an event a token that was already dead.
MIN_INVITATION_WINDOW = _dt.timedelta(days=7)


def invitation_expiry(event, now=None):
    """When a speaker invitation for ``event`` should stop working.

    The end of the day *after* the event, so an invitation can never lapse
    before the speaker needs it. The old fixed 30-day TTL could: Derek Hook was
    invited 2026-07-27 for the 2026-09-06 event and his link expired 2026-08-26,
    eleven days early. A lapsed invitation is not self-recoverable — the account
    has no usable password, so Django's password reset silently skips it (see
    the ``auth-email-scanner-and-reset-gotchas`` memory) and staff must reissue.

    Falls back to ``SpeakerInvitation.DEFAULT_TTL`` when there's no date to work
    from, and is floored at ``MIN_INVITATION_WINDOW``.
    """
    now = now or timezone.now()
    final_date = None
    if event is not None:
        last = event.sessions.order_by("start_at").last()
        if last is not None:
            final_date = timezone.localtime(last.end_at).date()
        elif event.end_date:
            final_date = event.end_date
    if final_date is None:
        return now + SpeakerInvitation.DEFAULT_TTL
    day_after = _dt.datetime.combine(final_date + _dt.timedelta(days=1), _dt.time.max)
    expiry = timezone.make_aware(day_after, timezone.get_current_timezone())
    return max(expiry, now + MIN_INVITATION_WINDOW)


def _split_name(name: str) -> tuple[str, str]:
    name = (name or "").strip()
    if " " in name:
        first, last = name.rsplit(" ", 1)
        return first, last
    return name, ""


def default_invitation_message(speaker: Speaker, event) -> str:
    """The pre-filled, editable note the PC sees in the confirm panel."""
    return (
        f"You are warmly invited to present at {event.title}. We use our own "
        "in-site video meeting for the event, so we would like to set you up "
        "with a login here on the Lacanian School website."
    )


def provision_login(speaker: Speaker) -> User:
    """Return the login for this external speaker, creating one if needed.

    Idempotent: links an existing user with the speaker's email rather than
    duplicating. New users are external (off the directory), non-public, with an
    unusable password until they activate via the invitation token.
    """
    if speaker.user_id:
        return speaker.user
    email = (speaker.email or "").strip().lower()
    if not email:
        raise ValueError("Speaker has no email to invite.")
    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        first, last = _split_name(speaker.name)
        user = User.objects.create_user(
            email=email, first_name=first, last_name=last,
        )
        # New login: keep it off the directory and unusable until activation.
        user.set_unusable_password()
        user.save(update_fields=["password"])
        profile = user.profile
        profile.role = Profile.Role.EXTERNAL
        profile.public = False
        profile.save(update_fields=["role", "public"])
    speaker.user = user
    speaker.save(update_fields=["user"])
    return user


def send_invitation(speaker: Speaker, event, message: str) -> SpeakerInvitation:
    """Provision-or-link the login, mint/refresh the token, send the email."""
    user = provision_login(speaker)
    expires_at = invitation_expiry(event)
    inv = SpeakerInvitation.objects.filter(speaker=speaker, user=user).first()
    if inv is None:
        inv = SpeakerInvitation.objects.create(
            speaker=speaker, user=user, expires_at=expires_at,
        )
    else:
        # Re-derive on every resend — refresh() would otherwise fall back to the
        # fixed default and quietly reintroduce the too-short window.
        inv.refresh(expires_at=expires_at)
    base = settings.SITE_BASE_URL.rstrip("/")
    activation_url = base + reverse("events:speaker_invitation_accept", args=[inv.token])
    event_url = base + reverse("events:detail", args=[event.slug])
    body = render_to_string("events/email/speaker_invitation.txt", {
        "speaker": speaker,
        "event": event,
        "message": message,
        "activation_url": activation_url,
        "event_url": event_url,
        "support_email": settings.SUPPORT_EMAIL,
    })
    EmailMessage(
        subject=f"Invitation to present at {event.title}",
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
        reply_to=[settings.SUPPORT_EMAIL],
    ).send(fail_silently=False)
    return inv
