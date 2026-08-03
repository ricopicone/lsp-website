"""Registration payment plans (task #501)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.models import Profile, User
from events.models import Audience, Event, PriceTier, PricingCode
from events.pricing import resolve_price

pytestmark = pytest.mark.django_db


def _user(email="member@example.com"):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    return u


def _event(title="Seminar", **kwargs):
    today = timezone.localdate()
    return Event.objects.create(
        title=title,
        slug=title.lower().replace(" ", "-"),
        event_type=Event.Type.SEMINAR,
        start_date=today + timedelta(days=7),
        end_date=today + timedelta(days=90),
        published=True,
        status=Event.Status.OPEN,
        **kwargs,
    )


def _tier(event, amount="500.00", **kwargs):
    return PriceTier.objects.create(
        event=event, audience=Audience.ALL,
        base_amount=Decimal(amount), **kwargs,
    )


def _code(event, issuer, **kwargs):
    kwargs.setdefault("pricing_mode", PricingCode.Mode.FULL_PRICE)
    kwargs.setdefault("amount_or_percent", Decimal("0"))
    return PricingCode.objects.create(event=event, issued_by=issuer, **kwargs)


# ---- Task 1: the code carries a count and a full-price mode -------------


def test_installments_defaults_to_one():
    issuer = _user("faculty@example.com")
    event = _event()
    code = _code(event, issuer)
    assert code.installments == 1


def test_plain_code_resolution_is_unchanged():
    """installments=1 must resolve byte-identically to today."""
    issuer = _user("faculty@example.com")
    member = _user()
    event = _event()
    tier = _tier(event)
    code = _code(
        event, issuer,
        pricing_mode=PricingCode.Mode.PERCENT_OFF,
        amount_or_percent=Decimal("20"),
    )
    r = resolve_price(user=member, tier=tier, pricing_code=code)
    assert r.amount == Decimal("400.00")
    assert r.installments == 1


def test_full_price_mode_returns_the_tier_base():
    issuer = _user("faculty@example.com")
    member = _user()
    event = _event()
    tier = _tier(event)
    code = _code(event, issuer, installments=3)
    r = resolve_price(user=member, tier=tier, pricing_code=code)
    assert r.amount == Decimal("500.00")
    assert r.installments == 3
    assert code.code in r.explanation


def test_a_discount_and_a_plan_are_independent_axes():
    issuer = _user("faculty@example.com")
    member = _user()
    event = _event()
    tier = _tier(event)
    code = _code(
        event, issuer,
        pricing_mode=PricingCode.Mode.PERCENT_OFF,
        amount_or_percent=Decimal("20"),
        installments=3,
    )
    r = resolve_price(user=member, tier=tier, pricing_code=code)
    assert r.amount == Decimal("400.00")   # the plan did not change the total
    assert r.installments == 3


def test_installment_count_is_bounded():
    from django.core.exceptions import ValidationError
    issuer = _user("faculty@example.com")
    event = _event()
    code = PricingCode(
        event=event, issued_by=issuer,
        pricing_mode=PricingCode.Mode.FULL_PRICE,
        amount_or_percent=Decimal("0"),
        installments=0,
    )
    with pytest.raises(ValidationError):
        code.clean()
    code.installments = 13
    with pytest.raises(ValidationError):
        code.clean()
    code.installments = 3
    code.clean()   # no raise


# ---- Task 2: the installment model --------------------------------------


def _registration(user, event, tier, amount="500.00", **kwargs):
    from registrations.models import Registration
    kwargs.setdefault("status", Registration.Status.AWAITING_PAYMENT)
    return Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal(amount), **kwargs,
    )


def test_installment_rows_hang_off_the_registration():
    from payments.models import RegistrationInstallment
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier)
    inst = RegistrationInstallment.objects.create(
        registration=reg, sequence=1,
        due_date=timezone.localdate(), amount=Decimal("166.66"),
    )
    assert list(reg.installments.all()) == [inst]
    assert inst.paid is False

    inst.mark_paid()
    inst.refresh_from_db()
    assert inst.paid is True
    assert inst.paid_at is not None

    before = inst.paid_at
    inst.mark_paid()          # idempotent
    inst.refresh_from_db()
    assert inst.paid_at == before


def test_installment_sequence_is_unique_per_registration():
    from django.db import IntegrityError
    from payments.models import RegistrationInstallment
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier)
    RegistrationInstallment.objects.create(
        registration=reg, sequence=1,
        due_date=timezone.localdate(), amount=Decimal("250.00"),
    )
    with pytest.raises(IntegrityError):
        RegistrationInstallment.objects.create(
            registration=reg, sequence=1,
            due_date=timezone.localdate(), amount=Decimal("250.00"),
        )


def test_a_payment_can_point_at_an_installment():
    from payments.models import Payment, RegistrationInstallment
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier)
    inst = RegistrationInstallment.objects.create(
        registration=reg, sequence=1,
        due_date=timezone.localdate(), amount=Decimal("166.66"),
    )
    p = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, registration=reg,
        user=member, amount=Decimal("166.66"),
        registration_installment=inst,
    )
    assert list(inst.payments.all()) == [p]


# ---- Task 3: the schedule module ----------------------------------------


def test_schedule_sums_to_the_exact_fee_with_the_remainder_last():
    from payments import registration_plans
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier, "500.00")

    rows = registration_plans.build_schedule(reg, 3, today=date(2026, 9, 1))
    assert [r.amount for r in rows] == [
        Decimal("166.66"), Decimal("166.66"), Decimal("166.68"),
    ]
    assert sum(r.amount for r in rows) == Decimal("500.00")
    assert [r.due_date for r in rows] == [
        date(2026, 9, 1), date(2026, 10, 1), date(2026, 11, 1),
    ]


def test_build_schedule_is_idempotent():
    from payments import registration_plans
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier)

    first = registration_plans.build_schedule(reg, 3, today=date(2026, 9, 1))
    again = registration_plans.build_schedule(reg, 5, today=date(2026, 9, 1))
    assert len(first) == 3
    assert len(again) == 3
    assert reg.installments.count() == 3


def test_build_schedule_declines_degenerate_input():
    from payments import registration_plans
    member = _user()
    event = _event()
    tier = _tier(event)

    reg = _registration(member, event, tier)
    assert registration_plans.build_schedule(reg, 1) == []
    assert reg.installments.count() == 0

    free = _registration(_user("free@example.com"), event, tier, "0.00")
    assert registration_plans.build_schedule(free, 3) == []


def test_plan_readers():
    from payments import registration_plans
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier, "300.00")

    assert registration_plans.is_on_plan(reg) is False
    registration_plans.build_schedule(reg, 3, today=date(2026, 9, 1))
    assert registration_plans.is_on_plan(reg) is True
    assert registration_plans.outstanding(reg) == Decimal("300.00")

    first = registration_plans.next_unpaid(reg)
    assert first.sequence == 1
    first.mark_paid()
    assert registration_plans.next_unpaid(reg).sequence == 2
    assert registration_plans.outstanding(reg) == Decimal("200.00")


def test_due_installment_prefers_the_oldest_overdue():
    from payments import registration_plans
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier, "300.00")
    registration_plans.build_schedule(reg, 3, today=date(2026, 9, 1))

    # Nothing due a month before the schedule starts.
    assert registration_plans.due_installment(reg, date(2026, 8, 1)) is None
    # Within the lead window ahead of #1.
    assert registration_plans.due_installment(reg, date(2026, 8, 28)).sequence == 1
    # #1 unpaid and overdue wins over #2 falling due.
    assert registration_plans.due_installment(reg, date(2026, 10, 1)).sequence == 1

    reg.installments.filter(sequence=1).update(paid=True)
    assert registration_plans.due_installment(reg, date(2026, 10, 1)).sequence == 2
    reg.installments.update(paid=True)
    assert registration_plans.due_installment(reg, date(2026, 12, 1)) is None


# ---- Task 4: settlement --------------------------------------------------


def _settle(reg, installment):
    """Pay one installment the way the Stripe webhook does."""
    from payments.models import Payment
    from payments.operations import complete_payment
    p = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, registration=reg,
        user=reg.user, amount=installment.amount,
        method=Payment.Method.STRIPE, status=Payment.Status.PENDING,
        registration_installment=installment,
        stripe_payment_intent_id=f"pi_test_{installment.pk}",
    )
    complete_payment(p)
    return p


def test_a_plan_mints_one_charge_for_the_whole_fee():
    from payments import registration_plans
    from payments.models import Charge
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier, "500.00")
    rows = registration_plans.build_schedule(reg, 3, today=timezone.localdate())

    _settle(reg, rows[0])
    charges = Charge.objects.filter(registration=reg)
    assert charges.count() == 1
    # The full fee, not the $166.66 that actually moved.
    assert charges.first().amount == Decimal("500.00")

    _settle(reg, rows[1])
    _settle(reg, rows[2])
    assert Charge.objects.filter(registration=reg).count() == 1


def test_a_non_plan_registration_mints_exactly_what_it_did_before():
    from payments.models import Charge, Payment
    from payments.operations import complete_payment
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier, "500.00")
    p = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, registration=reg,
        user=member, amount=Decimal("500.00"),
        method=Payment.Method.STRIPE, status=Payment.Status.PENDING,
        stripe_payment_intent_id="pi_test_plain",
    )
    complete_payment(p)
    assert Charge.objects.get(registration=reg).amount == Decimal("500.00")


def test_settling_an_installment_marks_it_and_grants_access():
    from registrations.models import Registration
    from payments import registration_plans
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier, "300.00")
    rows = registration_plans.build_schedule(reg, 3, today=timezone.localdate())

    _settle(reg, rows[0])
    rows[0].refresh_from_db()
    reg.refresh_from_db()
    assert rows[0].paid is True
    # Access follows the first payment — the existing AWAITING_PAYMENT flip.
    assert reg.status == Registration.Status.PAID
    assert registration_plans.outstanding(reg) == Decimal("200.00")


def test_the_ledger_reads_partial_until_the_last_installment():
    from payments import registration_plans
    from payments.ledger import member_account
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier, "300.00")
    rows = registration_plans.build_schedule(reg, 3, today=timezone.localdate())

    _settle(reg, rows[0])
    assert member_account(member)["balance"] == Decimal("200.00")

    _settle(reg, rows[1])
    assert member_account(member)["balance"] == Decimal("100.00")

    _settle(reg, rows[2])
    assert member_account(member)["balance"] == Decimal("0.00")


# ---- Task 5: redemption builds the schedule ------------------------------


def test_redeeming_a_plan_code_builds_the_schedule(client, monkeypatch):
    from registrations.models import Registration
    member = _user()
    issuer = _user("faculty@example.com")
    event = _event()
    tier = _tier(event, "500.00")
    code = _code(event, issuer, installments=3)

    sessions = []

    def _fake(installment):
        from payments.models import Payment
        p = Payment.objects.create(
            payment_type=Payment.Type.REGISTRATION,
            registration=installment.registration,
            user=installment.registration.user, amount=installment.amount,
            method=Payment.Method.STRIPE, status=Payment.Status.PENDING,
            registration_installment=installment,
        )
        sessions.append(p)
        return p, type("S", (), {"url": "https://stripe.test/session"})()

    monkeypatch.setattr(
        "registrations.views.create_registration_installment_session", _fake,
    )

    client.force_login(member)
    resp = client.post(
        f"/events/{event.slug}/register/",
        {"price_tier": tier.pk, "pricing_code": code.code},
    )
    assert resp.status_code == 302

    reg = Registration.objects.get(user=member, event=event)
    assert reg.quoted_amount == Decimal("500.00")      # the full fee
    assert reg.installments.count() == 3
    # Checkout was opened for installment 1 only.
    assert len(sessions) == 1
    assert sessions[0].amount == Decimal("166.66")


def test_an_approval_gated_plan_builds_its_schedule_on_approval():
    from registrations.models import Registration
    member = _user()
    issuer = _user("faculty@example.com")
    event = _event(requires_faculty_approval=True)
    tier = _tier(event, "300.00")
    code = _code(event, issuer, installments=3)

    reg = _registration(
        member, event, tier, "300.00",
        status=Registration.Status.PENDING_APPROVAL, pricing_code=code,
    )
    assert reg.installments.count() == 0

    reg.approve(issuer)
    reg.refresh_from_db()
    assert reg.status == Registration.Status.AWAITING_PAYMENT
    assert reg.installments.count() == 3


def test_a_declined_plan_registration_builds_no_schedule():
    from registrations.models import Registration
    member = _user()
    issuer = _user("faculty@example.com")
    event = _event(requires_faculty_approval=True)
    tier = _tier(event, "300.00")
    code = _code(event, issuer, installments=3)
    reg = _registration(
        member, event, tier, "300.00",
        status=Registration.Status.PENDING_APPROVAL, pricing_code=code,
    )
    reg.decline(issuer, "no")
    assert reg.installments.count() == 0


# ---- Task 6: paying the rest ---------------------------------------------


def test_a_member_can_pay_a_later_installment(client, monkeypatch):
    from payments import registration_plans
    from registrations.models import Registration
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(
        member, event, tier, "300.00", status=Registration.Status.PAID,
    )
    rows = registration_plans.build_schedule(reg, 3, today=timezone.localdate())
    rows[0].mark_paid()

    called = {}

    def _fake(installment):
        called["seq"] = installment.sequence
        return None, type("S", (), {"url": "https://stripe.test/session"})()

    monkeypatch.setattr(
        "registrations.views.create_registration_installment_session", _fake,
    )

    client.force_login(member)
    resp = client.post(f"/registrations/installments/{rows[1].pk}/pay/")
    assert resp.status_code == 302
    assert called["seq"] == 2


def test_paying_a_paid_installment_is_a_no_op(client):
    from payments import registration_plans
    from registrations.models import Registration
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(
        member, event, tier, "300.00", status=Registration.Status.PAID,
    )
    rows = registration_plans.build_schedule(reg, 3, today=timezone.localdate())
    rows[0].mark_paid()

    client.force_login(member)
    resp = client.post(f"/registrations/installments/{rows[0].pk}/pay/")
    assert resp.status_code == 302
    assert f"/registrations/{reg.pk}/confirmation/" in resp["Location"]


def test_another_member_cannot_pay_your_installment(client):
    from payments import registration_plans
    from registrations.models import Registration
    member = _user()
    intruder = _user("intruder@example.com")
    event = _event()
    tier = _tier(event)
    reg = _registration(
        member, event, tier, "300.00", status=Registration.Status.PAID,
    )
    rows = registration_plans.build_schedule(reg, 3, today=timezone.localdate())

    client.force_login(intruder)
    resp = client.post(f"/registrations/installments/{rows[0].pk}/pay/")
    assert resp.status_code == 404


def test_the_confirmation_page_shows_the_schedule(client):
    from payments import registration_plans
    from registrations.models import Registration
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(
        member, event, tier, "300.00", status=Registration.Status.PAID,
    )
    rows = registration_plans.build_schedule(reg, 3, today=timezone.localdate())
    rows[0].mark_paid()

    client.force_login(member)
    body = client.get(f"/registrations/{reg.pk}/confirmation/").content.decode()
    assert "payment plan" in body.lower()
    assert "$200.00" in body            # still to pay
    assert "you're all set" not in body.lower()
