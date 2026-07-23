"""send_registration_reminders skips removed/resigned/deceased members
(task #451 safety belt) — they shouldn't be nagged to pay for a
registration after they've left the school."""

from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.core import mail
from django.core.management import call_command
from django.utils import timezone

from accounts.models import Profile, User
from events.models import Audience, Event, PriceTier
from registrations.models import Registration

pytestmark = pytest.mark.django_db


def _registration(email, standing=None, deceased=False):
    user = User.objects.create_user(email=email, password="x")
    if standing:
        user.profile.standing = standing
    if deceased:
        user.profile.deceased_on = date(2026, 1, 1)
    user.profile.save()
    user.refresh_from_db()
    event = Event.objects.create(
        title=f"Seminar for {email}", slug=f"seminar-{email.split('@')[0]}",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
    )
    tier = PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("60.00"),
    )
    reg = Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("60.00"),
        status=Registration.Status.AWAITING_PAYMENT,
        decided_at=timezone.now() - timedelta(days=10),
    )
    return user, reg


def test_reminder_sent_to_active_member_awaiting_payment():
    user, reg = _registration("active-reg@example.com")
    call_command("send_registration_reminders", stdout=StringIO())
    assert len(mail.outbox) == 1
    reg.refresh_from_db()
    assert reg.reminded_at is not None


def test_reminder_skips_removed_member():
    user, reg = _registration(
        "removed-reg@example.com", standing=Profile.Standing.REMOVED,
    )
    call_command("send_registration_reminders", stdout=StringIO())
    assert len(mail.outbox) == 0
    reg.refresh_from_db()
    assert reg.reminded_at is None


def test_reminder_skips_resigned_member():
    user, reg = _registration(
        "resigned-reg@example.com", standing=Profile.Standing.RESIGNED,
    )
    call_command("send_registration_reminders", stdout=StringIO())
    assert len(mail.outbox) == 0


def test_reminder_skips_deceased_member():
    user, reg = _registration("deceased-reg@example.com", deceased=True)
    assert user.is_active is False  # Task 1's sync
    call_command("send_registration_reminders", stdout=StringIO())
    assert len(mail.outbox) == 0
