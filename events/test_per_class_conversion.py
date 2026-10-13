"""Per-class codes on a whole-seminar event, and converting registrations to
them (tasks #810/#811).

The fixtures are shaped like event 25 on prod: a $500 whole-seminar event
where most people pay the seminar price, and four redeemed a $25 fixed code
that faculty meant as $25 a class.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.urls import reverse
from django.utils import timezone

from events import per_class
from events.forms import PricingCodeForm
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
HOUR = timedelta(hours=1)


@pytest.fixture
def seminar_25():
    event = make_event(per_class=False)
    tier = make_tier(event, amount="500")
    faculty = make_user("matthew@example.com")
    whole = enroll(make_user("whole@example.com"), event, tier, rate=None)
    whole.quoted_amount = Decimal("500")
    whole.save()
    four = []
    for i in range(4):
        user = make_user(f"r{i}@example.com")
        code = PricingCode.objects.create(
            event=event, issued_by=faculty,
            pricing_mode=PricingCode.Mode.FIXED_AMOUNT, amount_or_percent=Decimal("25"),
        )
        reg = enroll(user, event, tier, rate=None, pricing_code=code)
        reg.quoted_amount = Decimal("25")
        reg.save()
        Payment.objects.create(
            payment_type=Payment.Type.REGISTRATION, registration=reg, user=user,
            amount=Decimal("25"), status=Payment.Status.SUCCEEDED,
            method=Payment.Method.STRIPE, stripe_payment_intent_id=f"pi_{i}",
        )
        Charge.objects.create(
            user=user, category="registration", amount=Decimal("25"),
            effective_date=timezone.localdate(), registration=reg,
        )
        four.append(reg)
    return event, whole, four


def _convert(regs, *extra):
    out = StringIO()
    args = []
    for r in regs:
        args += ["--registration", str(r.pk)]
    call_command("convert_to_per_class", *args,
                 "--bill-from", timezone.localdate().isoformat(), *extra, stdout=out)
    return out.getvalue()


# ---- conversion -----------------------------------------------------------------


def test_dry_run_reports_and_changes_nothing(seminar_25):
    event, whole, four = seminar_25
    out = _convert(four, "--dry-run")
    assert out.count("-> $25.00/class") == 4
    assert "Dry run" in out
    assert not Registration.objects.filter(per_class_rate__isnull=False).exists()
    assert not Charge.objects.filter(status="void").exists()


def test_conversion_moves_only_the_named_registrations(seminar_25):
    event, whole, four = seminar_25
    _convert(four)
    event.refresh_from_db()
    assert not event.is_per_class                     # the seminar is unchanged
    assert event.price_tiers.get().base_amount == Decimal("500")
    whole.refresh_from_db()
    assert not whole.is_per_class and whole.quoted_amount == Decimal("500")
    for reg in four:
        reg.refresh_from_db()
        assert reg.per_class_rate == Decimal("25")
        assert reg.quoted_amount == Decimal("0")
        assert reg.status == Registration.Status.PAID
        assert reg.charges.get().status == Charge.Status.VOID
        assert reg.pricing_code.per_class
    assert Notification.objects.filter(category="registration_status").count() == 4


def test_the_25_paid_covers_the_first_class_and_only_converts_bill(seminar_25):
    event, whole, four = seminar_25
    _convert(four)
    session = make_session(event, ends_ago=-timedelta(days=1))   # tomorrow
    per_class.run(now=session.end_at + HOUR)
    per_class.run(now=session.end_at + per_class.WINDOW + HOUR)
    assert ClassAttendance.objects.count() == 4                   # not `whole`
    assert per_class.open_balance(four[0]) == Decimal("0")
    session2 = make_session(event, ends_ago=-timedelta(days=15))
    per_class.run(now=session2.end_at + HOUR)
    per_class.run(now=session2.end_at + per_class.WINDOW + HOUR)
    assert per_class.open_balance(four[0]) == Decimal("25.00")


def test_classes_before_bill_from_are_not_recorded(seminar_25):
    event, whole, four = seminar_25
    make_session(event, ends_ago=timedelta(days=2))
    _convert(four)
    per_class.run()
    assert not ClassAttendance.objects.exists()


def test_a_registration_without_a_code_needs_a_rate(seminar_25):
    event, whole, four = seminar_25
    with pytest.raises(CommandError, match="--rate"):
        _convert([whole])
    _convert([whole], "--rate", "40")
    whole.refresh_from_db()
    assert whole.per_class_rate == Decimal("40")


def test_refuses_an_already_per_class_registration(seminar_25):
    event, whole, four = seminar_25
    _convert(four[:1])
    with pytest.raises(CommandError, match="already per class"):
        _convert(four[:1])


# ---- per-class codes on a whole-seminar event -------------------------------------


def test_a_per_class_code_must_name_its_rate():
    event = make_event(per_class=False)
    pct = PricingCodeForm(data={"pricing_mode": "percent_off", "amount_or_percent": "20",
                                "per_class": "on"}, event=event)
    assert not pct.is_valid() and "pricing_mode" in pct.errors
    fixed = PricingCodeForm(data={"pricing_mode": "fixed_amount", "amount_or_percent": "25",
                                  "per_class": "on"}, event=event)
    assert fixed.is_valid(), fixed.errors


def test_registering_with_a_per_class_code_enrolls_per_class(client):
    event = make_event(per_class=False)
    tier = make_tier(event, amount="500")
    code = PricingCode.objects.create(
        event=event, issued_by=make_user("f@example.com"),
        pricing_mode=PricingCode.Mode.FIXED_AMOUNT, amount_or_percent=Decimal("25"),
        per_class=True,
    )
    user = make_user()
    client.force_login(user)
    resp = client.post(reverse("registrations:register", args=[event.slug]),
                       {"price_tier": tier.id, "pricing_code": code.code})
    assert resp.status_code == 302
    reg = Registration.objects.get(user=user)
    assert reg.per_class_rate == Decimal("25")
    assert reg.quoted_amount == Decimal("0")
    assert reg.status == Registration.Status.PAID
    assert reg.per_class_since is not None


def test_the_code_box_switches_an_unpaid_place_to_per_class(client):
    event = make_event(per_class=False)
    tier = make_tier(event, amount="500")
    user = make_user()
    reg = enroll(user, event, tier, rate=None, status=Registration.Status.AWAITING_PAYMENT)
    reg.quoted_amount = Decimal("500")
    reg.save()
    code = PricingCode.objects.create(
        event=event, issued_by=make_user("f@example.com"),
        pricing_mode=PricingCode.Mode.FIXED_AMOUNT, amount_or_percent=Decimal("25"),
        per_class=True, restricted_to_user=user,
    )
    client.force_login(user)
    # A pinned per-class code is offered, never applied on its own.
    client.get(reverse("registrations:confirm", args=[reg.id]))
    reg.refresh_from_db()
    assert not reg.is_per_class
    client.post(reverse("registrations:apply_code", args=[reg.id]), {"pricing_code": code.code})
    reg.refresh_from_db()
    assert reg.per_class_rate == Decimal("25")
    assert reg.status == Registration.Status.PAID
    assert reg.quoted_amount == Decimal("0")


def test_faculty_tools_show_attendance_for_a_mixed_event(client, seminar_25):
    event, whole, four = seminar_25
    _convert(four)
    staff = make_user("pc@example.com")
    staff.is_staff = True
    staff.save()
    client.force_login(staff)
    body = client.get(reverse("events:detail", args=[event.slug]) + "?view=faculty",
                      follow=True).content.decode()
    assert 'id="attendance"' in body
