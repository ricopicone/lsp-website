"""Paying next year's dues before the year starts (task #625).

A member wrote in asking how to pay before September 1. Tuition had gained an
early-pay path in task #450 phase B (``_resolve_tuition_period`` accepts the
current *or* the upcoming period); dues never did, and the paid-up page told
members outright that the next cycle opens later.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, User
from payments.models import Charge, DuesPeriod, Payment
from payments.testing import make_period

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def stub_stripe(monkeypatch):
    stub = MagicMock(return_value=MagicMock(id="cs_dues_x", url="https://stripe.test/dues"))
    monkeypatch.setattr("payments.views.create_dues_session", stub)
    return stub


@pytest.fixture
def periods(db):
    """A current dues year and the next one, with nothing else in the way."""
    DuesPeriod.objects.all().delete()
    today = timezone.localdate()
    current = DuesPeriod.objects.create(
        name="AY 2025–2026", slug="ay-2025-2026-x",
        start_date=today - timedelta(days=200),
        due_date=today - timedelta(days=170),
        end_date=today + timedelta(days=15),
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"),
        dues_amount_analyst=Decimal("150"),
    )
    upcoming = make_period(DuesPeriod, 
        name="AY 2026–2027", slug="ay-2026-2027-x",
        start_date=today + timedelta(days=16),
        due_date=today + timedelta(days=46),
        end_date=today + timedelta(days=380),
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"),
        dues_amount_analyst=Decimal("150"),
    )
    return current, upcoming


@pytest.fixture
def member(db):
    u = User.objects.create_user(email="early@x.test", password="x")
    u.profile.role = Profile.Role.CANDIDATE
    u.profile.save()
    return u


# ---- The period lookup ------------------------------------------------------

def test_upcoming_returns_the_next_year_not_the_current_one(periods):
    current, upcoming = periods
    assert DuesPeriod.current() == current
    assert DuesPeriod.upcoming() == upcoming


def test_upcoming_is_none_when_no_future_year_exists(periods):
    _current, upcoming = periods
    upcoming.delete()
    assert DuesPeriod.upcoming() is None


# ---- Paying next year -------------------------------------------------------

def test_post_with_upcoming_slug_binds_the_payment_to_next_year(
    client, member, periods,
):
    _current, upcoming = periods
    client.force_login(member)
    response = client.post(reverse("dues"), {"period": upcoming.slug})

    assert response.status_code == 302
    payment = Payment.objects.get(user=member, payment_type=Payment.Type.DUES)
    assert payment.dues_period == upcoming
    assert payment.amount == Decimal("100")


def test_a_paid_up_member_can_actually_complete_the_early_payment(
    client, member, periods,
):
    """The already-paid short-circuit reads ``dues_state``, which is hardwired
    to the *current* year (payments/ledger.py:247). Left global it would swallow
    the POST for next year and hand the member the paid-up page again, which is
    the very dead end this task exists to remove."""
    current, upcoming = periods
    Payment.objects.create(
        user=member, payment_type=Payment.Type.DUES, amount=Decimal("100"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        dues_period=current, paid_at=timezone.now(),
    )
    Charge.objects.create(
        user=member, category=Charge.Category.DUES, amount=Decimal("100"),
        effective_date=current.start_date, dues_period=current,
    )
    client.force_login(member)
    response = client.post(reverse("dues"), {"period": upcoming.slug})

    assert response.status_code == 302
    assert response.url == "https://stripe.test/dues"
    assert Payment.objects.filter(
        user=member, dues_period=upcoming, status=Payment.Status.PENDING,
    ).exists()


def test_post_without_a_slug_still_pays_the_current_year(client, member, periods):
    current, _upcoming = periods
    client.force_login(member)
    client.post(reverse("dues"))

    assert Payment.objects.get(user=member).dues_period == current


def test_post_with_an_unrelated_slug_falls_back_to_the_current_year(
    client, member, periods,
):
    """A stale or hand-typed slug must never bind money to an arbitrary year."""
    current, _upcoming = periods
    old = DuesPeriod.objects.create(
        name="AY 2019–2020", slug="ay-2019-2020-x",
        start_date=current.start_date - timedelta(days=2000),
        due_date=current.start_date - timedelta(days=1990),
        end_date=current.start_date - timedelta(days=1700),
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"),
        dues_amount_analyst=Decimal("150"),
    )
    client.force_login(member)
    client.post(reverse("dues"), {"period": old.slug})

    assert Payment.objects.get(user=member).dues_period == current


def test_paid_up_member_is_offered_next_year_instead_of_a_closed_door(
    client, member, periods,
):
    """The paid-up page used to say 'The next cycle opens after that', which is
    what read as 'the portal is not available until Sep 1'."""
    current, upcoming = periods
    Payment.objects.create(
        user=member, payment_type=Payment.Type.DUES, amount=Decimal("100"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        dues_period=current, paid_at=timezone.now(),
    )
    client.force_login(member)
    body = client.get(reverse("dues")).content.decode()

    assert "The next cycle opens after that" not in body
    assert upcoming.name in body
    assert f'value="{upcoming.slug}"' in body


def test_double_payment_guard_is_per_year(client, member, periods):
    """Paying next year early must not make this year look already paid, nor
    let next year be paid twice."""
    _current, upcoming = periods
    Payment.objects.create(
        user=member, payment_type=Payment.Type.DUES, amount=Decimal("100"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        dues_period=upcoming, paid_at=timezone.now(),
    )
    client.force_login(member)
    body = client.get(reverse("dues")).content.decode()

    # This year is still payable...
    assert "Continue to payment" in body
    # ...but next year is not offered again.
    assert f'value="{upcoming.slug}"' not in body


# ---- The charge follows the money, not the calendar -------------------------

def test_settling_an_early_payment_mints_the_charge(member, periods):
    """sync_dues_charges refuses future periods on purpose, so an early payment
    would otherwise read as loose credit until September. The charge is minted
    when the money actually lands, mirroring mint_registration_charge."""
    from payments.operations import complete_payment

    _current, upcoming = periods
    payment = Payment.objects.create(
        user=member, payment_type=Payment.Type.DUES, amount=Decimal("100"),
        status=Payment.Status.PENDING, method=Payment.Method.OFFLINE,
        dues_period=upcoming,
    )
    complete_payment(payment)

    charge = Charge.objects.get(
        user=member, category=Charge.Category.DUES, dues_period=upcoming,
    )
    assert charge.amount == Decimal("100")
    assert charge.effective_date == upcoming.start_date


def test_settling_never_double_mints_against_the_sync(member, periods):
    """The nightly sync and the settle path must not both mint the same year."""
    from payments.charges import sync_dues_charges
    from payments.operations import complete_payment

    current, _upcoming = periods
    sync_dues_charges(current)
    assert Charge.objects.filter(user=member, dues_period=current).count() == 1

    payment = Payment.objects.create(
        user=member, payment_type=Payment.Type.DUES, amount=Decimal("100"),
        status=Payment.Status.PENDING, method=Payment.Method.OFFLINE,
        dues_period=current,
    )
    complete_payment(payment)

    assert Charge.objects.filter(user=member, dues_period=current).count() == 1


def test_a_dues_payment_with_no_period_mints_nothing(member, periods):
    """Undated dues (no period configured) has no year to bill."""
    from payments.operations import complete_payment

    payment = Payment.objects.create(
        user=member, payment_type=Payment.Type.DUES, amount=Decimal("100"),
        status=Payment.Status.PENDING, method=Payment.Method.OFFLINE,
    )
    complete_payment(payment)

    assert not Charge.objects.filter(user=member, category=Charge.Category.DUES).exists()


# ---- The receipt says which year ------------------------------------------

def test_checkout_line_item_names_the_year(member, periods):
    """An early payment's receipt must say which year it bought."""
    from payments.stripe_checkout import create_dues_session

    _current, upcoming = periods
    payment = Payment.objects.create(
        user=member, payment_type=Payment.Type.DUES, amount=Decimal("100"),
        status=Payment.Status.PENDING, method=Payment.Method.STRIPE,
        dues_period=upcoming,
    )
    with pytest.MonkeyPatch.context() as mp:
        captured = {}

        def fake_make_session(**kwargs):
            captured.update(kwargs)
            return MagicMock(id="cs_x", url="https://stripe.test/x")

        mp.setattr("payments.stripe_checkout._make_session", fake_make_session)
        create_dues_session(payment)

    assert upcoming.name in captured["product_description"]
