"""Converting a whole-seminar event to per-class billing (tasks #810/#811).

The fixture is shaped like event 25: a $300 seminar, and members who each
redeemed a $25 fixed code once and were enrolled for the whole year.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from events import per_class
from events.models import ClassAttendance, PricingCode
from events.per_class_fixtures import (
    enroll,
    make_event,
    make_session,
    make_tier,
    make_user,
)
from notifications.models import Notification
from payments.models import Charge, Payment
from registrations.models import Registration

pytestmark = pytest.mark.django_db


@pytest.fixture
def seminar_25():
    event = make_event(per_class=False)
    tier = make_tier(event, amount="300")
    faculty = make_user("matthew@example.com")
    code = PricingCode.objects.create(
        event=event, issued_by=faculty, pricing_mode=PricingCode.Mode.FIXED_AMOUNT,
        amount_or_percent=Decimal("25"),
    )
    regs = []
    for i in range(4):
        user = make_user(f"r{i}@example.com")
        reg = enroll(user, event, tier, rate=None, pricing_code=code)
        reg.quoted_amount = Decimal("25")
        reg.save()
        pay = Payment.objects.create(
            payment_type=Payment.Type.REGISTRATION, registration=reg, user=user,
            amount=Decimal("25"), status=Payment.Status.SUCCEEDED,
            method=Payment.Method.STRIPE, stripe_payment_intent_id=f"pi_{i}",
        )
        Charge.objects.create(
            user=user, category="registration", amount=Decimal("25"),
            effective_date=timezone.localdate(), registration=reg,
        )
        assert pay
        regs.append(reg)
    return event, regs


def _convert(event, *extra):
    out = StringIO()
    bill_from = timezone.localdate().isoformat()
    call_command("convert_event_to_per_class", event.slug, "--price", "25",
                 "--bill-from", bill_from, *extra, stdout=out)
    return out.getvalue()


def test_dry_run_reports_and_changes_nothing(seminar_25):
    event, regs = seminar_25
    out = _convert(event, "--dry-run")
    assert "$25.00/class" in out or "$25/class" in out
    assert "Dry run" in out
    event.refresh_from_db()
    assert not event.is_per_class
    assert Charge.objects.filter(status="void").count() == 0


def test_conversion_moves_everyone_in_place(seminar_25):
    event, regs = seminar_25
    _convert(event)
    event.refresh_from_db()
    assert event.is_per_class
    assert event.price_tiers.get().base_amount == Decimal("25")
    for reg in regs:
        reg.refresh_from_db()
        assert reg.is_per_class and reg.per_class_rate == Decimal("25")
        assert reg.quoted_amount == Decimal("0")
        assert reg.status == Registration.Status.PAID
        assert reg.charges.get().status == Charge.Status.VOID
        assert "per-class billing" in reg.staff_notes
    assert Notification.objects.filter(category="registration_status").count() == 4


def test_the_25_already_paid_covers_the_first_class(seminar_25):
    event, regs = seminar_25
    _convert(event)
    reg = regs[0]
    for days in (2, 1):
        session = make_session(event, ends_ago=timedelta(hours=1))
        session.start_at += timedelta(days=days)
        session.end_at += timedelta(days=days)
        session.save()
    # Two future classes, recorded and billed once they've passed.
    later = timezone.now() + timedelta(days=6)
    per_class.run(now=later - timedelta(days=3, hours=12))
    per_class.run(now=later)
    assert ClassAttendance.objects.filter(registration=reg).count() == 2
    assert per_class.open_balance(reg) == Decimal("25.00")


def test_classes_before_bill_from_are_not_billed(seminar_25):
    event, regs = seminar_25
    make_session(event, ends_ago=timedelta(days=2))
    _convert(event)
    per_class.run()
    assert not ClassAttendance.objects.exists()


def test_refuses_a_plan_code(seminar_25):
    event, regs = seminar_25
    PricingCode.objects.create(
        event=event, issued_by=regs[0].user, pricing_mode=PricingCode.Mode.FULL_PRICE,
        amount_or_percent=0, installments=3,
    )
    with pytest.raises(CommandError, match="installments"):
        _convert(event)
    event.refresh_from_db()
    assert not event.is_per_class


def test_a_registration_without_a_code_gets_the_new_price():
    event = make_event(per_class=False)
    tier = make_tier(event, amount="300")
    reg = enroll(make_user(), event, tier, rate=None)
    _convert(event)
    reg.refresh_from_db()
    assert reg.per_class_rate == Decimal("25")
