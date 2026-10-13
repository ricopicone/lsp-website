"""Registering on a per-class event, and the skip-list (task #811).

A per-class registration is a $0 enrolled row carrying ``per_class_rate``;
every existing path keyed on ``quoted_amount`` must leave it alone.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, User
from events.models import PricingCode
from events.per_class_fixtures import enroll, make_event, make_tier, make_user
from payments import coverage
from payments.models import Payment, TuitionEnrollment, TuitionPeriod
from registrations.models import Registration
from registrations.services import (
    auto_apply_pinned_code,
    comp_registration,
    remove_registration,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def no_stripe():
    with patch("registrations.views.create_checkout_session") as stub:
        stub.side_effect = AssertionError("per-class registration hit Stripe")
        yield stub


def _register(client, user, event, **data):
    client.force_login(user)
    return client.post(reverse("registrations:register", args=[event.slug]), data)


def test_fixed_rate_enrolls_at_zero_with_the_rate(client):
    event = make_event()
    tier = make_tier(event)
    user = make_user()
    resp = _register(client, user, event, price_tier=tier.id)
    assert resp.status_code == 302
    reg = Registration.objects.get(user=user, event=event)
    assert reg.status == Registration.Status.PAID
    assert reg.quoted_amount == Decimal("0")
    assert reg.per_class_rate == Decimal("25.00")
    assert not reg.installments.exists()


def test_sliding_rate_is_what_the_member_chose(client):
    event = make_event()
    tier = make_tier(event, amount="40", sliding_scale=True, minimum_amount=Decimal("10"))
    user = make_user()
    _register(client, user, event, price_tier=tier.id, sliding_amount="15")
    reg = Registration.objects.get(user=user)
    assert reg.per_class_rate == Decimal("15.00")


def test_a_fixed_code_sets_the_rate(client):
    event = make_event()
    tier = make_tier(event, amount="40")
    faculty = make_user("faculty@example.com")
    code = PricingCode.objects.create(
        event=event, issued_by=faculty, pricing_mode=PricingCode.Mode.FIXED_AMOUNT,
        amount_or_percent=Decimal("25"), max_uses=4,
    )
    user = make_user()
    _register(client, user, event, price_tier=tier.id, pricing_code=code.code)
    reg = Registration.objects.get(user=user)
    assert reg.per_class_rate == Decimal("25.00")
    code.refresh_from_db()
    assert code.uses_remaining == 3


def test_a_plan_code_is_refused_on_a_per_class_event(client):
    event = make_event()
    tier = make_tier(event, amount="40")
    code = PricingCode.objects.create(
        event=event, issued_by=make_user("f@example.com"),
        pricing_mode=PricingCode.Mode.FULL_PRICE, amount_or_percent=0,
        installments=3,
    )
    user = make_user()
    resp = _register(client, user, event, price_tier=tier.id, pricing_code=code.code)
    assert resp.status_code == 200
    assert not Registration.objects.filter(user=user).exists()


def test_approval_holds_a_per_class_registration_then_enrolls(client):
    event = make_event(requires_faculty_approval=True)
    tier = make_tier(event)
    user = make_user()
    _register(client, user, event, price_tier=tier.id)
    reg = Registration.objects.get(user=user)
    assert reg.status == Registration.Status.PENDING_APPROVAL
    assert reg.approve(make_user("faculty@example.com"))
    reg.refresh_from_db()
    assert reg.status == Registration.Status.PAID
    assert not reg.installments.exists()


def test_rate_ignores_tuition_for_a_covered_tier(client):
    """A non-current member on a covered tier gets the base rate; coverage is
    decided when each class is billed, not here."""
    event = make_event()
    tier = make_tier(event, covered_by_tuition=True)
    user = make_user()
    _register(client, user, event, price_tier=tier.id)
    assert Registration.objects.get(user=user).per_class_rate == Decimal("25.00")


# ---- the skip-list ---------------------------------------------------------


def test_self_cancel_of_a_converted_registration_never_refunds():
    """Review focus 2: a converted registration still holds the $25 Stripe
    payment it was made with; cancelling must not send it back."""
    event = make_event()
    tier = make_tier(event)
    user = make_user()
    reg = enroll(user, event, tier)
    Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, registration=reg, user=user,
        amount=Decimal("25"), status=Payment.Status.SUCCEEDED,
        method=Payment.Method.STRIPE, stripe_payment_intent_id="pi_x",
    )
    with patch("payments.refund.stripe.Refund.create") as create:
        issued = reg.cancel()
    assert issued is None
    create.assert_not_called()
    reg.refresh_from_db()
    assert reg.status == Registration.Status.CANCELLED


def test_removal_leaves_no_money_for_the_treasurer():
    event = make_event()
    tier = make_tier(event)
    user = make_user()
    reg = enroll(user, event, tier)
    Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, registration=reg, user=user,
        amount=Decimal("25"), status=Payment.Status.SUCCEEDED,
        method=Payment.Method.STRIPE, stripe_payment_intent_id="pi_x",
    )
    staff = make_user("registrar@example.com")
    with patch("payments.refund.stripe.Refund.create") as create:
        result = remove_registration(reg, staff, refund=True)
    create.assert_not_called()
    assert result.removed and not result.refunded
    assert result.left_money == Decimal("0")


def test_comp_accepts_an_enrolled_per_class_registration():
    event = make_event()
    reg = enroll(make_user(), event, make_tier(event))
    comped, _ = comp_registration(reg, make_user("registrar@example.com"))
    assert comped
    reg.refresh_from_db()
    assert reg.status == Registration.Status.COMPED
    assert not reg.charges.exists()


def test_comp_still_refuses_a_paid_whole_seminar_registration():
    event = make_event(per_class=False)
    tier = make_tier(event, amount="300")
    reg = enroll(make_user(), event, tier, rate=None)
    comped, _ = comp_registration(reg, make_user("registrar@example.com"))
    assert not comped


def test_a_pinned_lower_code_lowers_the_rate():
    event = make_event()
    tier = make_tier(event, amount="40")
    user = make_user()
    reg = enroll(user, event, tier, rate="40")
    code = PricingCode.objects.create(
        event=event, issued_by=make_user("f@example.com"),
        pricing_mode=PricingCode.Mode.FIXED_AMOUNT, amount_or_percent=Decimal("15"),
        restricted_to_user=user,
    )
    assert auto_apply_pinned_code(reg) == code
    reg.refresh_from_db()
    assert reg.per_class_rate == Decimal("15")
    assert reg.quoted_amount == Decimal("0")
    assert reg.status == Registration.Status.PAID


def test_the_code_box_sets_the_rate(client):
    event = make_event()
    tier = make_tier(event, amount="40")
    user = make_user()
    reg = enroll(user, event, tier, rate="40")
    code = PricingCode.objects.create(
        event=event, issued_by=make_user("f@example.com"),
        pricing_mode=PricingCode.Mode.PERCENT_OFF, amount_or_percent=Decimal("50"),
    )
    client.force_login(user)
    client.post(reverse("registrations:apply_code", args=[reg.id]), {"pricing_code": code.code})
    reg.refresh_from_db()
    assert reg.per_class_rate == Decimal("20.00")
    assert reg.status == Registration.Status.PAID


# ---- tuition coverage ---------------------------------------------------------


@pytest.fixture
def period():
    TuitionPeriod.objects.all().delete()
    return TuitionPeriod.objects.create(
        name="AY 2026–2027", slug="ay-2026-2027-pc",
        start_date=date(2026, 9, 1), decision_due_date=date(2026, 10, 31),
        end_date=date(2027, 8, 31), tuition_amount=Decimal("800.00"),
    )


def _covered_per_class(period):
    user = User.objects.create_user(email="pc-student@x.test", password="x")
    user.profile.role = Profile.Role.CANDIDATE
    user.profile.save()
    event = make_event(start_date=date(2026, 10, 1), end_date=date(2027, 5, 1))
    tier = make_tier(event, covered_by_tuition=True)
    reg = enroll(user, event, tier, rate="25")
    reg.quoted_explanation = coverage.COVERED_EXPLANATION
    reg.save()
    return user, reg


def test_whole_seminar_rebill_ignores_a_per_class_registration(period):
    """Review focus 1: skipping must not re-quote the per-class registration
    as if it were a covered whole seminar."""
    user, reg = _covered_per_class(period)
    assert coverage.covered_registrations(user, period) == []
    assert coverage.bill_skipped_coverage(user, period) == []
    reg.refresh_from_db()
    assert reg.quoted_amount == Decimal("0")
    assert reg.status == Registration.Status.PAID


def test_apply_coverage_ignores_a_per_class_registration(period):
    user, reg = _covered_per_class(period)
    TuitionEnrollment.objects.create(
        user=user, tuition_period=period, status=TuitionEnrollment.Status.COMMITTED,
    )
    assert coverage.apply_coverage(user, period) == []


def test_covered_member_on_per_class_event_gets_the_uncovered_rate(client):
    """The covered short-circuit stores what a class would cost uncovered, so a
    skipped year bills the right figure."""
    today = timezone.localdate()
    TuitionPeriod.objects.all().delete()
    period = TuitionPeriod.objects.create(
        name="AY test", slug="ay-test-pc",
        start_date=today - timedelta(days=60), decision_due_date=today,
        end_date=today + timedelta(days=300), tuition_amount=Decimal("800"),
    )
    user = make_user("covered@example.com", role=Profile.Role.CANDIDATE)
    TuitionEnrollment.objects.create(
        user=user, tuition_period=period, status=TuitionEnrollment.Status.COMMITTED,
    )
    event = make_event(start_date=today, end_date=today + timedelta(days=90))
    make_tier(event, amount="30", covered_by_tuition=True)
    client.force_login(user)
    client.post(
        reverse("registrations:register", args=[event.slug]),
        {"confirm_covered": "1"},
    )
    reg = Registration.objects.get(user=user)
    assert reg.per_class_rate == Decimal("30")
    assert reg.quoted_amount == Decimal("0")
