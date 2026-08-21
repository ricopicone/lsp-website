"""Staff removal of a registration (task #627).

The console's Remove button releases a place and asks separately whether to
refund; anything the site cannot refund cleanly becomes the treasurer's.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from accounts.models import User
from events.models import Audience, Event, PriceTier
from payments.models import Payment
from registrations.models import Registration


@pytest.fixture
def event(db):
    return Event.objects.create(
        title="Removable", slug="removable",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
        published=True, status=Event.Status.OPEN,
    )


@pytest.fixture
def tier(event):
    return PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("300.00"),
    )


@pytest.fixture
def member(db):
    return User.objects.create_user(email="member@example.com")


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(email="registrar@example.com")


def _reg(event, tier, member, status, amount="300.00"):
    return Registration.objects.create(
        user=member, event=event, price_tier=tier,
        quoted_amount=Decimal(amount), status=status,
    )


@pytest.fixture
def awaiting_registration(event, tier, member):
    return _reg(event, tier, member, Registration.Status.AWAITING_PAYMENT)


@pytest.fixture
def paid_registration(event, tier, member):
    reg = _reg(event, tier, member, Registration.Status.PAID)
    Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, registration=reg, user=member,
        amount=Decimal("300.00"), status=Payment.Status.SUCCEEDED,
        method=Payment.Method.STRIPE, stripe_payment_intent_id="pi_removal",
    )
    return reg


@pytest.fixture
def offline_paid_registration(event, tier, member):
    reg = _reg(event, tier, member, Registration.Status.PAID)
    Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, registration=reg, user=member,
        amount=Decimal("300.00"), status=Payment.Status.SUCCEEDED,
        method=Payment.Method.OFFLINE,
    )
    return reg


@pytest.fixture
def plan_registration(event, tier, member):
    from payments.registration_plans import build_schedule

    reg = _reg(event, tier, member, Registration.Status.PAID)
    build_schedule(reg, 3)
    return reg


def _fake_refund(cents=30000):
    fake = MagicMock(id="re_removal", amount=cents)
    fake.__getitem__ = lambda self, k: {"id": "re_removal", "amount": cents}[k]
    return fake


# ---- Task 1: cancel() splits releasing the place from refunding -----------


@pytest.mark.django_db
def test_cancel_without_refund_leaves_stripe_alone(paid_registration):
    with patch("payments.refund.stripe.Refund.create") as create:
        issued = paid_registration.cancel(refund=False)
    assert issued is None
    create.assert_not_called()
    paid_registration.refresh_from_db()
    assert paid_registration.status == Registration.Status.CANCELLED


@pytest.mark.django_db
def test_cancel_without_refund_works_on_a_payment_plan(plan_registration):
    """The PlanRefundRequiresTreasurer guard lives inside the refund branch,
    so declining the refund is what makes a plan registration removable."""
    plan_registration.cancel(refund=False)
    plan_registration.refresh_from_db()
    assert plan_registration.status == Registration.Status.CANCELLED


@pytest.mark.django_db
def test_cancel_without_refund_works_on_an_offline_payment(
    offline_paid_registration,
):
    """cancel() raises RuntimeError looking for a Stripe payment it can
    refund; not refunding never goes looking."""
    offline_paid_registration.cancel(refund=False)
    offline_paid_registration.refresh_from_db()
    assert offline_paid_registration.status == Registration.Status.CANCELLED


@pytest.mark.django_db
def test_cancel_still_refunds_by_default(paid_registration):
    """The member's self-cancel path is unchanged."""
    fake = _fake_refund()
    with patch(
        "payments.refund.stripe.Refund.create", return_value=fake,
    ) as create:
        issued = paid_registration.cancel()
    create.assert_called_once_with(payment_intent="pi_removal")
    assert issued is fake
    paid_registration.refresh_from_db()
    assert paid_registration.status == Registration.Status.REFUNDED


# ---- Task 2: the treasurer handoff ---------------------------------------


@pytest.fixture
def treasurer(db):
    from core.models import StaffRole

    user = User.objects.create_user(email="treasurer@example.com")
    role, _ = StaffRole.objects.get_or_create(
        key=StaffRole.TREASURER, defaults={"name": "Treasurer"},
    )
    role.holders.add(user)
    return user


@pytest.mark.django_db
def test_removal_left_money_notifies_the_treasurer(
    paid_registration, staff_user, treasurer,
):
    from notifications.models import Notification
    from payments.notifications import removal_left_money

    removal_left_money(paid_registration, Decimal("300.00"), staff_user)

    note = Notification.objects.filter(recipient=treasurer).first()
    assert note is not None
    assert "300.00" in note.body
    assert paid_registration.user.email in note.body or (
        paid_registration.user.get_full_name() in note.body
    )


@pytest.mark.django_db
def test_removal_left_money_survives_a_vacant_treasurer_role(
    paid_registration, staff_user,
):
    """No holder must not raise — the removal has already happened."""
    from payments.notifications import removal_left_money

    removal_left_money(paid_registration, Decimal("300.00"), staff_user)
