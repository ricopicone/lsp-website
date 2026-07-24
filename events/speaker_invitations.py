"""External-speaker invitation: provision-or-link a login, mint a token, send
the invitation email (task #463). Kept separate from the event views so the
provisioning logic is testable in isolation."""
from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, User

from .models import Speaker, SpeakerInvitation


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
    inv = SpeakerInvitation.objects.filter(speaker=speaker, user=user).first()
    if inv is None:
        inv = SpeakerInvitation.objects.create(
            speaker=speaker, user=user,
            expires_at=timezone.now() + SpeakerInvitation.DEFAULT_TTL,
        )
    else:
        inv.refresh()
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
