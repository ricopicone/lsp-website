"""Shared builders for the video tests (mirrors events/test_seminar_workspace)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.test import override_settings

from accounts.models import Profile, User
from events.models import Audience, Event, PriceTier
from registrations.models import Registration

# Settings that make services.daily_enabled() True.
daily_on = override_settings(
    DAILY_ENABLED=True,
    DAILY_API_KEY="test-key",
    DAILY_DOMAIN="lsp.daily.co",
    DAILY_TOKEN_TTL_MINUTES=180,
    DAILY_MAX_PARTICIPANTS=0,
)


def user(email, *, is_faculty=False):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.is_faculty = is_faculty
    u.profile.save()
    return u


def seminar(slug="sem"):
    return Event.objects.create(
        title="Seminar on the Letter", slug=slug,
        event_type=Event.Type.SEMINAR,
        start_date=date(2026, 9, 1), end_date=date(2027, 5, 1),
    )


def special_event(slug="special"):
    return Event.objects.create(
        title="Working with Masochism", slug=slug,
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2026, 11, 1), end_date=date(2026, 11, 1),
    )


def register(u, event, status=Registration.Status.PAID):
    tier = event.price_tiers.first() or PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("0.00")
    )
    return Registration.objects.create(
        user=u, event=event, price_tier=tier,
        quoted_amount=Decimal("0.00"), status=status,
    )


def video_channel(slug="vid", *, access=None, workgroup=None):
    from parletre.models import Channel

    return Channel.objects.create(
        name="Video room", slug=slug, kind=Channel.Kind.VIDEO,
        access=access or Channel.Access.OPEN, workgroup=workgroup,
    )
