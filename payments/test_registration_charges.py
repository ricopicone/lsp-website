"""Registration charges mint at settle time, never from abandoned checkouts (task #439)."""

from datetime import date
from decimal import Decimal

import pytest

from accounts.models import User
from events.models import Audience, Event, PriceTier
from payments import charges
from payments.models import Charge, Payment
from payments.operations import complete_payment
from registrations.models import Registration

pytestmark = pytest.mark.django_db


@pytest.fixture
def member():
    return User.objects.create_user(email="rc@x.test", password="x")


@pytest.fixture
def registration(member):
    # Minimal event + registration, same idiom as payments/test_webhook.py.
    event = Event.objects.create(
        title="Seminar X", slug="seminar-x",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
    )
    tier = PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("60.00"),
    )
    return Registration.objects.create(
        user=member, event=event, price_tier=tier,
        quoted_amount=Decimal("60.00"),
    )


def test_complete_payment_mints_open_charge(member, registration):
    p = Payment.objects.create(
        user=member, payment_type=Payment.Type.REGISTRATION,
        registration=registration, amount=Decimal("60"),
        method=Payment.Method.STRIPE,
    )
    complete_payment(p)
    c = Charge.objects.get(registration=registration)
    assert c.status == Charge.Status.OPEN
    assert c.amount == Decimal("60")
    assert c.user_id == member.id
    complete_payment(p)                      # idempotent
    assert Charge.objects.filter(registration=registration).count() == 1


def test_zero_amount_payment_mints_nothing(member, registration):
    registration.quoted_amount = Decimal("0")
    registration.save()
    p = Payment.objects.create(
        user=member, payment_type=Payment.Type.REGISTRATION,
        registration=registration, amount=Decimal("0"),
        method=Payment.Method.OFFLINE,
    )
    complete_payment(p)
    assert Charge.objects.filter(registration=registration).count() == 0


def test_comp_mints_pre_waived_charge(member, registration):
    c = charges.mint_comped_charge(registration)
    assert c.status == Charge.Status.WAIVED
    assert c.amount == registration.quoted_amount
    assert charges.mint_comped_charge(registration).id == c.id  # idempotent


def test_void_on_refund(member, registration):
    p = Payment.objects.create(
        user=member, payment_type=Payment.Type.REGISTRATION,
        registration=registration, amount=Decimal("60"),
        method=Payment.Method.OFFLINE,
    )
    complete_payment(p)
    charges.void_registration_charge(registration, "Refunded.")
    c = Charge.objects.get(registration=registration)
    assert c.status == Charge.Status.VOID
    assert "Refunded." in c.notes
