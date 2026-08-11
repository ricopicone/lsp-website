"""Coverage re-billing (task #485) — what tuition coverage bought a member in a
year, and what each of those registrations is worth if the year ends up skipped.

Plus the other direction (task #561): what coverage owes a member the moment a
paying decision is recorded, including the registrations they made *before* it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import Profile, User
from events.models import Audience, Event, PriceTier
from payments import coverage
from payments.models import TuitionEnrollment, TuitionPeriod
from registrations.models import Registration

pytestmark = pytest.mark.django_db


@pytest.fixture
def period():
    TuitionPeriod.objects.all().delete()   # seed migration pre-populates periods
    return TuitionPeriod.objects.create(
        name="AY 2026–2027", slug="ay-2026-2027-cov",
        start_date=date(2026, 9, 1), decision_due_date=date(2026, 10, 31),
        end_date=date(2027, 8, 31), tuition_amount=Decimal("800.00"),
    )


@pytest.fixture
def student():
    u = User.objects.create_user(email="cov-student@x.test", password="x")
    u.profile.role = Profile.Role.CANDIDATE
    u.profile.save()
    return u


def _event(slug, start=date(2026, 10, 1)):
    return Event.objects.create(
        title=slug.title(), slug=slug, start_date=start, end_date=start,
        status=Event.Status.OPEN, published=True,
    )


def _tier(event, *, amount="200.00", covered=True, sliding=False, minimum="0.00"):
    return PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal(amount),
        covered_by_tuition=covered, sliding_scale=sliding,
        minimum_amount=Decimal(minimum),
    )


def _reg(student, tier, *, status=Registration.Status.PAID, amount="0.00",
         code=None, explanation=None):
    return Registration.objects.create(
        user=student, event=tier.event, price_tier=tier, pricing_code=code,
        quoted_amount=Decimal(amount),
        quoted_explanation=(
            coverage.COVERED_EXPLANATION if explanation is None else explanation
        ),
        status=status,
    )


def _quoted(student, slug, amount="200.00", start=date(2026, 10, 1)):
    """A registration quoted the regular fee — what task #561 is about.

    It carries no re-bill marker, because nothing ever re-billed it: it was
    created before a covering decision existed.
    """
    return _reg(
        student, _tier(_event(slug, start=start), amount=amount),
        status=Registration.Status.AWAITING_PAYMENT, amount=amount,
        explanation="Standard All price.",
    )


@pytest.fixture
def committed(period, student):
    """A covering decision for the year — what makes coverage apply."""
    return TuitionEnrollment.objects.create(
        user=student, tuition_period=period,
        status=TuitionEnrollment.Status.COMMITTED,
    )


@pytest.fixture
def staff_user(db):
    """Mirrors the fixture in payments/test_tuition.py:447."""
    u = User.objects.create_user(email="cov-staff@x.test", password="x")
    u.is_staff = True
    u.save()
    return u


def test_retro_amount_is_the_listed_price_for_a_flat_tier(period):
    tier = _tier(_event("flat"), amount="200.00")
    assert coverage.retro_amount(tier) == Decimal("200.00")


def test_retro_amount_is_the_floor_for_a_sliding_tier(period):
    """A skipping member would have picked their own figure at or above the
    floor, so assume the floor rather than the top."""
    tier = _tier(_event("slide"), amount="200.00", sliding=True, minimum="60.00")
    assert coverage.retro_amount(tier) == Decimal("60.00")


def test_covered_registrations_finds_a_covered_zero_registration(period, student):
    reg = _reg(student, _tier(_event("seminar-a")))
    assert coverage.covered_registrations(student, period) == [reg]


def test_covered_registrations_excludes_another_academic_year(period, student):
    _reg(student, _tier(_event("last-year", start=date(2025, 10, 1))))
    assert coverage.covered_registrations(student, period) == []


def test_covered_registrations_excludes_a_comp(period, student):
    """A comp is already charge-backed by mint_comped_charge, and it is not
    tuition coverage."""
    _reg(student, _tier(_event("comped")), status=Registration.Status.COMPED)
    assert coverage.covered_registrations(student, period) == []


def test_covered_registrations_excludes_a_pricing_code_freebie(period, student):
    """A code that zeroed the fee is not tuition coverage. PricingCode has no
    "free" mode — 100 percent off is how a free code is expressed."""
    from events.models import PricingCode

    tier = _tier(_event("codefree"))
    code = PricingCode.objects.create(
        event=tier.event, code="FREE-1", issued_by=student,
        pricing_mode=PricingCode.Mode.PERCENT_OFF,
        amount_or_percent=Decimal("100"),
    )
    _reg(student, tier, code=code)
    assert coverage.covered_registrations(student, period) == []


def test_covered_registrations_excludes_a_cancelled_registration(period, student):
    _reg(student, _tier(_event("gone")), status=Registration.Status.CANCELLED)
    assert coverage.covered_registrations(student, period) == []


def test_covered_registrations_excludes_a_paid_nonzero_registration(period, student):
    """Someone who paid the regular fee owes nothing extra."""
    _reg(student, _tier(_event("paidfor")), amount="200.00")
    assert coverage.covered_registrations(student, period) == []


# ---- bill / un-bill ---------------------------------------------------------

def test_billing_requotes_a_paid_registration(period, student):
    reg = _reg(student, _tier(_event("bill-me"), amount="200.00"))
    changed = coverage.bill_skipped_coverage(student, period)
    assert changed == [reg]
    reg.refresh_from_db()
    assert reg.quoted_amount == Decimal("200.00")
    assert reg.status == Registration.Status.AWAITING_PAYMENT
    assert reg.quoted_explanation == coverage.REBILLED_EXPLANATION
    assert reg.needs_payment is True      # the "Pay →" button renders
    assert "Re-billed $200.00" in reg.staff_notes


def test_billing_leaves_a_pending_approval_row_pending(period, student):
    """approve() routes on the amount, so the row must keep its status or it
    would skip the faculty approval it is waiting for."""
    reg = _reg(student, _tier(_event("await-approval"), amount="150.00"),
               status=Registration.Status.PENDING_APPROVAL)
    coverage.bill_skipped_coverage(student, period)
    reg.refresh_from_db()
    assert reg.status == Registration.Status.PENDING_APPROVAL
    assert reg.quoted_amount == Decimal("150.00")


def test_billing_is_idempotent(period, student):
    reg = _reg(student, _tier(_event("twice"), amount="200.00"))
    coverage.bill_skipped_coverage(student, period)
    assert coverage.bill_skipped_coverage(student, period) == []
    reg.refresh_from_db()
    assert reg.quoted_amount == Decimal("200.00")


def test_apply_coverage_restores_a_row_that_was_never_rebilled(
    period, student, committed,
):
    """Task #561: registered before the decision existed, so it was quoted the
    regular fee and carries no marker for a marker-match to find."""
    reg = _quoted(student, "quoted-early")
    changed = coverage.apply_coverage(student, period)
    assert [r.pk for r in changed] == [reg.pk]
    reg.refresh_from_db()
    assert reg.quoted_amount == Decimal("0")
    assert reg.status == Registration.Status.PAID    # access gate passes again
    assert reg.quoted_explanation == coverage.COVERED_EXPLANATION
    assert reg.needs_payment is False
    assert "Covered by tuition" in reg.staff_notes


def test_apply_coverage_restores_a_rebilled_row(period, student, committed):
    """The task #485 round trip still works — a re-billed row is a strict
    subset of what the predicate selects."""
    reg = _reg(student, _tier(_event("restore"), amount="200.00"))
    coverage.bill_skipped_coverage(student, period)
    changed = coverage.apply_coverage(student, period)
    assert [r.pk for r in changed] == [reg.pk]
    reg.refresh_from_db()
    assert reg.quoted_amount == Decimal("0")
    assert reg.status == Registration.Status.PAID
    assert reg.quoted_explanation == coverage.COVERED_EXPLANATION


def test_apply_coverage_needs_a_covering_enrollment(period, student):
    """No decision on file covers nothing."""
    _quoted(student, "no-decision")
    assert coverage.apply_coverage(student, period) == []


def test_apply_coverage_ignores_a_skipping_year(period, student):
    TuitionEnrollment.objects.create(
        user=student, tuition_period=period,
        status=TuitionEnrollment.Status.SKIPPING,
    )
    _quoted(student, "skipped-year")
    assert coverage.apply_coverage(student, period) == []


def test_apply_coverage_leaves_a_pending_approval_row_pending(
    period, student, committed,
):
    """approve() routes on the amount, so the row must keep its status."""
    reg = _reg(student, _tier(_event("await-ok"), amount="150.00"),
               status=Registration.Status.PENDING_APPROVAL, amount="150.00",
               explanation="Standard All price.")
    coverage.apply_coverage(student, period)
    reg.refresh_from_db()
    assert reg.status == Registration.Status.PENDING_APPROVAL
    assert reg.quoted_amount == Decimal("0")


def test_apply_coverage_leaves_a_paid_fee_alone(period, student, committed):
    """If they paid the fee and then commit to tuition, that is a refund
    conversation for the treasurer, not a silent unwind."""
    reg = _reg(student, _tier(_event("already-paid"), amount="200.00"),
               status=Registration.Status.PAID, amount="200.00",
               explanation="Standard All price.")
    assert coverage.apply_coverage(student, period) == []
    reg.refresh_from_db()
    assert reg.quoted_amount == Decimal("200.00")


def test_apply_coverage_ignores_a_pricing_code_row(period, student, committed):
    """A discounted place is the code's doing, not tuition's."""
    from events.models import PricingCode

    tier = _tier(_event("coded"), amount="200.00")
    code = PricingCode.objects.create(
        event=tier.event, code="HALF-1", issued_by=student,
        pricing_mode=PricingCode.Mode.PERCENT_OFF,
        amount_or_percent=Decimal("50"),
    )
    reg = _reg(student, tier, status=Registration.Status.AWAITING_PAYMENT,
               amount="100.00", code=code,
               explanation="50% off via code HALF-1.")
    assert coverage.apply_coverage(student, period) == []
    reg.refresh_from_db()
    assert reg.quoted_amount == Decimal("100.00")


def test_apply_coverage_ignores_another_academic_year(period, student, committed):
    _quoted(student, "other-yr", start=date(2025, 10, 1))
    assert coverage.apply_coverage(student, period) == []


def test_apply_coverage_expires_a_live_checkout_session(
    period, student, committed, monkeypatch,
):
    """A member returning to a stale tab would otherwise pay for a place they
    now hold for free, and complete_payment mints no Charge against it."""
    from payments.models import Payment

    reg = _quoted(student, "stale-tab", amount="500.00")
    payment = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, user=student, registration=reg,
        amount=Decimal("500.00"), method=Payment.Method.STRIPE,
        status=Payment.Status.PENDING,
        stripe_checkout_session_id="cs_test_561",
    )
    expired = []
    monkeypatch.setattr("stripe.checkout.Session.expire", expired.append)

    coverage.apply_coverage(student, period)

    assert expired == ["cs_test_561"]
    payment.refresh_from_db()
    assert payment.status == Payment.Status.ABANDONED


def test_a_free_covered_tier_owes_nothing(period, student):
    _reg(student, _tier(_event("free-tier"), amount="0.00"))
    assert coverage.bill_skipped_coverage(student, period) == []


# ---- notification ----------------------------------------------------------

def test_rebill_notification_names_the_count_and_total(period, student):
    from notifications.categories import Category
    from notifications.models import Notification
    from payments.notifications import notify_coverage_rebilled

    _reg(student, _tier(_event("notify-me"), amount="200.00"))
    # Pass the rows billing returned, exactly as the decision view does — a
    # stale in-memory copy would still read $0.
    billed = coverage.bill_skipped_coverage(student, period)
    notify_coverage_rebilled(student, period, billed)

    note = Notification.objects.get(
        recipient=student, category=Category.ACCOUNT_UPDATES,
    )
    assert "1 registration" in note.title
    assert "200.00" in note.title or "200.00" in note.body


def test_confirmation_page_explains_a_rebilled_registration(client, period, student):
    reg = _reg(student, _tier(_event("explain-me"), amount="200.00"))
    coverage.bill_skipped_coverage(student, period)
    client.force_login(student)
    body = client.get(
        reverse("registrations:confirm", args=[reg.pk])
    ).content.decode()
    assert "skipping tuition for the year" in body
    assert "restores the coverage" in body
