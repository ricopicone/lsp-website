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


# ---- Task 3: what the member is told -------------------------------------


@pytest.mark.django_db
def test_staff_removal_email_includes_the_reason(paid_registration, mailoutbox):
    from payments.emails import send_cancellation_email

    send_cancellation_email(
        paid_registration,
        reason="Removed at the faculty's request.",
        staff_removed=True,
    )
    assert "Removed at the faculty's request." in mailoutbox[0].body


@pytest.mark.django_db
def test_staff_removal_email_does_not_invite_re_registration(
    paid_registration, mailoutbox,
):
    """Inviting someone the faculty just removed to sign up again is the one
    thing this copy must not do."""
    from payments.emails import send_cancellation_email

    send_cancellation_email(paid_registration, staff_removed=True)
    assert "register again" not in mailoutbox[0].body


@pytest.mark.django_db
def test_self_cancel_email_still_invites_re_registration(
    paid_registration, mailoutbox,
):
    from payments.emails import send_cancellation_email

    send_cancellation_email(paid_registration)
    assert "register again" in mailoutbox[0].body


@pytest.mark.django_db
def test_cancellation_email_without_a_reason_has_no_blank_gap(
    paid_registration, mailoutbox,
):
    from payments.emails import send_cancellation_email

    send_cancellation_email(paid_registration, staff_removed=True)
    assert "\n\n\n" not in mailoutbox[0].body


# ---- Task 4: the remove_registration service -----------------------------


@pytest.fixture
def comped_registration(event, tier, member):
    reg = _reg(event, tier, member, Registration.Status.COMPED)
    from payments.charges import mint_comped_charge
    mint_comped_charge(reg)
    return reg


@pytest.mark.django_db
def test_remove_awaiting_payment(awaiting_registration, staff_user, mailoutbox):
    from registrations.services import remove_registration

    out = remove_registration(awaiting_registration, staff_user)

    assert out.removed and not out.refunded
    assert out.left_money == Decimal("0")
    awaiting_registration.refresh_from_db()
    assert awaiting_registration.status == Registration.Status.CANCELLED
    assert "Removed by registrar@example.com" in awaiting_registration.staff_notes


@pytest.mark.django_db
def test_remove_expires_an_open_checkout_session(awaiting_registration, staff_user):
    """A stale tab must not pay for a place that no longer exists (#561)."""
    from registrations.services import remove_registration

    with patch("payments.stripe_sync.expire_open_sessions") as expire:
        remove_registration(awaiting_registration, staff_user)
    expire.assert_called_once()


@pytest.mark.django_db
def test_remove_comped_voids_the_waived_charge(comped_registration, staff_user):
    from payments.models import Charge
    from registrations.services import remove_registration

    remove_registration(comped_registration, staff_user)

    assert not (
        Charge.objects.filter(registration=comped_registration)
        .exclude(status=Charge.Status.VOID)
        .exists()
    )


@pytest.mark.django_db
def test_remove_paid_with_refund(paid_registration, staff_user):
    from registrations.services import remove_registration

    with patch(
        "payments.refund.stripe.Refund.create", return_value=_fake_refund(),
    ) as create:
        out = remove_registration(paid_registration, staff_user, refund=True)

    create.assert_called_once()
    assert out.refunded
    assert out.refunded_amount == Decimal("300.00")
    assert out.left_money == Decimal("0")
    paid_registration.refresh_from_db()
    assert paid_registration.status == Registration.Status.REFUNDED


@pytest.mark.django_db
def test_remove_paid_without_refund_leaves_credit(
    paid_registration, staff_user, treasurer,
):
    from notifications.models import Notification
    from registrations.services import remove_registration

    with patch("payments.refund.stripe.Refund.create") as create:
        out = remove_registration(paid_registration, staff_user, refund=False)

    create.assert_not_called()
    assert out.left_money == Decimal("300.00")
    assert not out.refunded
    paid_registration.refresh_from_db()
    assert paid_registration.status == Registration.Status.CANCELLED
    assert Notification.objects.filter(recipient=treasurer).exists()


@pytest.mark.django_db
def test_remove_offline_payment_still_releases_the_place(
    offline_paid_registration, staff_user, treasurer,
):
    """A refund the site cannot issue must never block the removal."""
    from registrations.services import remove_registration

    out = remove_registration(offline_paid_registration, staff_user, refund=True)

    assert out.removed and not out.refunded
    assert out.left_money == Decimal("300.00")
    offline_paid_registration.refresh_from_db()
    assert offline_paid_registration.status == Registration.Status.CANCELLED


@pytest.mark.django_db
def test_remove_a_payment_plan_still_releases_the_place(
    plan_registration, staff_user,
):
    from registrations.services import remove_registration

    out = remove_registration(plan_registration, staff_user, refund=True)

    assert out.removed and not out.refunded
    plan_registration.refresh_from_db()
    assert plan_registration.status == Registration.Status.CANCELLED
    # The schedule survives for the treasurer to settle, and because
    # send_registration_reminders filters plan rows on status=PAID, leaving
    # it cannot nudge anyone.
    assert plan_registration.installments.exists()


@pytest.mark.django_db
def test_remove_is_idempotent(awaiting_registration, staff_user, mailoutbox):
    from registrations.services import remove_registration

    remove_registration(awaiting_registration, staff_user)
    before = len(mailoutbox)
    out = remove_registration(awaiting_registration, staff_user)

    assert not out.removed
    assert len(mailoutbox) == before


@pytest.mark.django_db
def test_remove_records_the_reason_in_staff_notes(awaiting_registration, staff_user):
    from registrations.services import remove_registration

    remove_registration(
        awaiting_registration, staff_user, reason="Faculty asked.",
    )
    awaiting_registration.refresh_from_db()
    assert "Faculty asked." in awaiting_registration.staff_notes
