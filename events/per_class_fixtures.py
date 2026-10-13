"""Builders shared by the per-class billing tests (task #811).

Not a test module (no ``test_`` prefix), so pytest does not collect it.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.utils import timezone

from accounts.models import Profile, User
from events.models import Audience, Event, PriceTier, Session
from registrations.models import Registration


def make_user(email="member@example.com", role=Profile.Role.ANALYST):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = role
    u.profile.save()
    return u


def make_event(title="Beyond Principle", *, per_class=True, **kwargs):
    today = timezone.localdate()
    kwargs.setdefault("event_type", Event.Type.SEMINAR)
    kwargs.setdefault("start_date", today - timedelta(days=30))
    kwargs.setdefault("end_date", today + timedelta(days=120))
    kwargs.setdefault("format", Event.Format.IN_PERSON)
    event = Event.objects.create(
        title=title,
        slug=title.lower().replace(" ", "-"),
        published=True,
        status=Event.Status.OPEN,
        billing_mode=(
            Event.BillingMode.PER_CLASS if per_class else Event.BillingMode.WHOLE
        ),
        **kwargs,
    )
    return event


def make_tier(event, amount="25.00", **kwargs):
    return PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal(amount),
        covered_by_tuition=kwargs.pop("covered_by_tuition", False), **kwargs,
    )


def make_session(event, *, ends_ago=timedelta(hours=1), length=timedelta(hours=2)):
    end = timezone.now() - ends_ago
    return Session.objects.create(event=event, start_at=end - length, end_at=end)


def local_session(event, day, *, start=time(17, 0), length=timedelta(hours=2)):
    """A session on a school-local calendar ``day`` starting at ``start``."""
    begin = timezone.make_aware(datetime.combine(day, start))
    return Session.objects.create(event=event, start_at=begin, end_at=begin + length)


def enroll(user, event, tier, *, rate="25.00", status=Registration.Status.PAID,
           created_ago=timedelta(days=40), **kwargs):
    reg = Registration.objects.create(
        user=user, event=event, price_tier=tier, quoted_amount=Decimal("0"),
        per_class_rate=None if rate is None else Decimal(rate),
        status=status, **kwargs,
    )
    when = timezone.now() - created_ago
    Registration.objects.filter(pk=reg.pk).update(
        created_at=when, per_class_since=when if rate is not None else None,
    )
    reg.refresh_from_db()
    return reg
