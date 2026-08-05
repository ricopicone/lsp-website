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
    kwargs.setdefault("event_type", Event.Type.SEMINAR)
    kwargs.setdefault("start_date", today + timedelta(days=7))
    kwargs.setdefault("end_date", today + timedelta(days=90))
    return Event.objects.create(
        title=title,
        slug=title.lower().replace(" ", "-"),
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


def _dated_event(start, end, title="Seminar"):
    return _event(title=title, start_date=start, end_date=end)


def test_schedule_sums_to_the_exact_fee_with_the_remainder_last():
    from payments import registration_plans
    member = _user()
    event = _dated_event(date(2026, 9, 1), date(2027, 5, 31))
    tier = _tier(event)
    reg = _registration(member, event, tier, "500.00")

    rows = registration_plans.build_schedule(reg, 3, today=date(2026, 9, 1))
    assert [r.amount for r in rows] == [
        Decimal("166.66"), Decimal("166.66"), Decimal("166.68"),
    ]
    assert sum(r.amount for r in rows) == Decimal("500.00")


# The spacing rule, against the three shapes the real 2026-27 program has.
# Payments are spread across the event's own run rather than falling monthly
# from registration, which bunched them at the front of a nine-month seminar.


def test_a_long_seminar_spreads_across_its_run():
    """Sept-May, the common shape. Two payments land fall and spring, four
    land two-and-two, nine land monthly — the named schedules fall out of the
    geometry rather than being special cases."""
    from payments import registration_plans
    event = _dated_event(date(2026, 9, 1), date(2027, 5, 31))
    tier = _tier(event)
    start = date(2026, 9, 1)

    def dates(count, email):
        reg = _registration(_user(email), event, tier, "900.00")
        return [r.due_date for r in
                registration_plans.build_schedule(reg, count, today=start)]

    assert dates(2, "a@example.com") == [date(2026, 9, 1), date(2027, 1, 15)]
    assert dates(4, "b@example.com") == [
        date(2026, 9, 1), date(2026, 11, 8), date(2027, 1, 15), date(2027, 3, 24),
    ]
    nine = dates(9, "c@example.com")
    assert nine[0] == date(2026, 9, 1)
    assert nine[-1] == date(2027, 4, 29)
    # Every gap is about a month, none bunched.
    gaps = {(nine[i + 1] - nine[i]).days for i in range(8)}
    assert gaps == {30}


def test_a_four_week_workshop_falls_back_to_monthly():
    """Oct 1-29 in the real program. Spreading two payments across 28 days
    would put them a fortnight apart; the floor holds them to a month."""
    from payments import registration_plans
    event = _dated_event(date(2026, 10, 1), date(2026, 10, 29), title="Workshop")
    tier = _tier(event)
    reg = _registration(_user(), event, tier, "500.00")
    rows = registration_plans.build_schedule(reg, 2, today=date(2026, 10, 1))
    assert [r.due_date for r in rows] == [date(2026, 10, 1), date(2026, 10, 29)]


def test_a_spring_group_spreads_across_its_own_run():
    """Jan 17 - Jun 20 in the real program. A named 'fall and spring' schedule
    could not describe this at all; even spreading needs no vocabulary."""
    from payments import registration_plans
    event = _dated_event(date(2027, 1, 17), date(2027, 6, 20), title="Spring Group")
    tier = _tier(event)
    reg = _registration(_user(), event, tier, "400.00")
    rows = registration_plans.build_schedule(reg, 2, today=date(2027, 1, 17))
    assert [r.due_date for r in rows] == [date(2027, 1, 17), date(2027, 4, 4)]


def test_the_last_payment_lands_before_the_event_ends():
    """The school shouldn't still be collecting after it has finished
    delivering. True for every count on a normal-length event."""
    from payments import registration_plans
    event = _dated_event(date(2026, 9, 1), date(2027, 5, 31))
    tier = _tier(event)
    for count in range(2, 10):
        reg = _registration(
            _user(f"m{count}@example.com"), event, tier, "900.00",
        )
        rows = registration_plans.build_schedule(reg, count, today=date(2026, 9, 1))
        assert rows[-1].due_date < event.end_date, count


def test_a_late_registration_falls_back_to_monthly():
    """Registering after the event ends leaves no span to spread over."""
    from payments import registration_plans
    event = _dated_event(date(2026, 9, 1), date(2026, 10, 1))
    tier = _tier(event)
    reg = _registration(_user(), event, tier, "300.00")
    rows = registration_plans.build_schedule(reg, 3, today=date(2026, 11, 1))
    assert [r.due_date for r in rows] == [
        date(2026, 11, 1), date(2026, 11, 29), date(2026, 12, 27),
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
    from payments import registration_plans
    from registrations.models import Registration
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


def test_redeeming_a_plan_code_builds_the_schedule(client):
    """The registration keeps the whole fee; only the payment is chunked.
    (Where redemption *lands* is asserted by
    ``test_redeeming_a_plan_code_lands_on_the_schedule_not_stripe``.)"""
    from registrations.models import Registration
    member = _user()
    issuer = _user("faculty@example.com")
    event = _dated_event(date(2026, 9, 1), date(2027, 5, 31))
    tier = _tier(event, "500.00")
    code = _code(event, issuer, installments=3)

    client.force_login(member)
    resp = client.post(
        f"/events/{event.slug}/register/",
        {"price_tier": tier.pk, "pricing_code": code.code},
    )
    assert resp.status_code == 302

    reg = Registration.objects.get(user=member, event=event)
    assert reg.quoted_amount == Decimal("500.00")      # the full fee
    assert [i.amount for i in reg.installments.all()] == [
        Decimal("166.66"), Decimal("166.66"), Decimal("166.68"),
    ]


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


# ---- Task 7: cancel refuses on a plan ------------------------------------


def test_a_plan_registration_refuses_self_cancel():
    from payments import registration_plans
    from payments.refund import PlanRefundRequiresTreasurer
    from registrations.models import Registration
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(
        member, event, tier, "300.00", status=Registration.Status.PAID,
    )
    registration_plans.build_schedule(reg, 3, today=timezone.localdate())

    with pytest.raises(PlanRefundRequiresTreasurer):
        reg.cancel()
    reg.refresh_from_db()
    assert reg.status == Registration.Status.PAID   # nothing moved


def test_the_cancel_view_tells_the_member_to_ask_the_treasurer(client):
    from core.models import StaffRole
    from notifications.models import Notification
    from payments import registration_plans
    from registrations.models import Registration
    member = _user()
    treasurer = _user("treasurer@example.com")
    role, _ = StaffRole.objects.get_or_create(
        key=StaffRole.TREASURER, defaults={"name": "Treasurer"},
    )
    role.holders.add(treasurer)

    event = _event()
    tier = _tier(event)
    reg = _registration(
        member, event, tier, "300.00", status=Registration.Status.PAID,
    )
    registration_plans.build_schedule(reg, 3, today=timezone.localdate())

    client.force_login(member)
    resp = client.post(f"/registrations/{reg.pk}/cancel/", follow=True)
    # The specific flash, not just the word "treasurer" somewhere in the chrome.
    assert "the treasurer handles the cancellation" in resp.content.decode().lower()
    reg.refresh_from_db()
    assert reg.status == Registration.Status.PAID
    assert Notification.objects.filter(recipient=treasurer).exists()


def test_an_ordinary_paid_registration_still_self_cancels(monkeypatch):
    from payments.models import Payment
    from registrations.models import Registration
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(
        member, event, tier, "300.00", status=Registration.Status.PAID,
    )
    Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, registration=reg, user=member,
        amount=Decimal("300.00"), method=Payment.Method.STRIPE,
        status=Payment.Status.SUCCEEDED, stripe_payment_intent_id="pi_ok",
    )
    monkeypatch.setattr(
        "payments.refund.refund_payment", lambda p: {"id": "re_test"},
    )
    reg.cancel()
    reg.refresh_from_db()
    assert reg.status == Registration.Status.REFUNDED


# ---- Task 8: installment reminders ---------------------------------------


def _run_reminders(**opts):
    from io import StringIO

    from django.core.management import call_command
    out = StringIO()
    call_command("send_registration_reminders", stdout=out, **opts)
    return out.getvalue()


def _plan_reg(days_ago=40, amount="300.00"):
    from payments import registration_plans
    from registrations.models import Registration
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(
        member, event, tier, amount, status=Registration.Status.PAID,
    )
    registration_plans.build_schedule(
        reg, 3, today=timezone.localdate() - timedelta(days=days_ago),
    )
    return reg


def test_an_overdue_installment_is_nudged(mailoutbox):
    reg = _plan_reg()
    _run_reminders()
    assert len(mailoutbox) == 1
    assert "payment" in mailoutbox[0].subject.lower()
    reg.refresh_from_db()
    assert reg.reminded_at is not None


def test_a_fully_paid_plan_is_not_nudged(mailoutbox):
    reg = _plan_reg()
    reg.installments.update(paid=True)
    _run_reminders()
    assert len(mailoutbox) == 0


def test_an_installment_far_in_the_future_is_not_nudged(mailoutbox):
    _plan_reg(days_ago=-60)
    _run_reminders()
    assert len(mailoutbox) == 0


def test_the_installment_nudge_is_throttled(mailoutbox):
    _plan_reg()
    _run_reminders()
    _run_reminders()
    assert len(mailoutbox) == 1


# ---- Task 9: faculty + treasurer surfaces --------------------------------


def test_the_mint_form_accepts_a_plan_without_a_discount():
    from events.forms import PricingCodeForm
    form = PricingCodeForm(data={
        "pricing_mode": PricingCode.Mode.FULL_PRICE,
        "installments": "3",
    })
    assert form.is_valid(), form.errors
    code = form.save(commit=False)
    assert code.installments == 3
    assert code.amount_or_percent == Decimal("0")


def test_the_mint_form_still_defaults_to_pay_in_full():
    """The new field must not become required — an existing POST omitting it
    still works (see the new-modelform-field-is-required-by-default memory)."""
    from events.forms import PricingCodeForm
    form = PricingCodeForm(data={
        "pricing_mode": PricingCode.Mode.PERCENT_OFF,
        "amount_or_percent": "20",
    })
    assert form.is_valid(), form.errors
    assert form.save(commit=False).installments == 1


def test_a_discount_mode_still_requires_an_amount():
    from events.forms import PricingCodeForm
    form = PricingCodeForm(data={"pricing_mode": PricingCode.Mode.FIXED_AMOUNT})
    assert not form.is_valid()
    assert "amount_or_percent" in form.errors


def test_the_faculty_roster_flags_a_plan_without_dollars(client):
    """The roster faculty actually use is the Workspace tab — a seminar's
    event page redirects there."""
    from payments import registration_plans
    from registrations.models import Registration
    faculty = _user("faculty@example.com")
    faculty.profile.is_faculty = True
    faculty.profile.save()
    member = _user()
    event = _event()
    event.add_faculty(faculty)
    tier = _tier(event)
    reg = _registration(
        member, event, tier, "300.00", status=Registration.Status.PAID,
    )
    registration_plans.build_schedule(reg, 3, today=timezone.localdate())

    client.force_login(faculty)
    resp = client.get(event.workgroup.get_absolute_url() + "?tab=roster")
    body = resp.content.decode()
    assert "On a plan" in body
    assert "$100.00" not in body       # no per-installment dollars
    assert "2 of 3" not in body        # no progress


def test_a_registration_without_a_plan_is_not_flagged(client):
    from registrations.models import Registration
    faculty = _user("faculty@example.com")
    faculty.profile.is_faculty = True
    faculty.profile.save()
    member = _user()
    event = _event()
    event.add_faculty(faculty)
    tier = _tier(event)
    _registration(member, event, tier, "300.00", status=Registration.Status.PAID)

    client.force_login(faculty)
    resp = client.get(event.workgroup.get_absolute_url() + "?tab=roster")
    assert "On a plan" not in resp.content.decode()


# ---- The mint form is reachable for BOTH offering types ------------------
#
# A reading group's conveners hold ORGANIZER, not FACULTY (task #495), and the
# Workspace tab renders the mint form while a *different* view handles the POST.
# These assert the two gates agree, for a seminar and a reading group alike.


def _offering(event_type, convener_role):
    """An offering event whose workgroup has one lead in ``convener_role``."""
    title = "Seminar" if event_type == Event.Type.SEMINAR else "Reading Group"
    event = _event(title=title, event_type=event_type)
    wg = event.ensure_workgroup()
    convener = _user(f"{event.slug}-convener@example.com")
    wg.add_member(convener, role=convener_role)
    assert wg.memberships.serving().filter(
        user=convener, role=convener_role,
    ).exists()
    return event, convener


@pytest.mark.parametrize("event_type,convener_role", [
    (Event.Type.SEMINAR, "faculty"),
    (Event.Type.READING_GROUP, "organizer"),
])
def test_the_convener_sees_the_mint_form(client, event_type, convener_role):
    event, convener = _offering(event_type, convener_role)
    client.force_login(convener)
    resp = client.get(event.workgroup.get_absolute_url() + "?tab=roster")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Generate a pricing code" in body
    assert "Number of payments" in body       # the task #501 field


@pytest.mark.parametrize("event_type,convener_role", [
    (Event.Type.SEMINAR, "faculty"),
    (Event.Type.READING_GROUP, "organizer"),
])
def test_the_convener_can_actually_mint_a_plan_code(
    client, event_type, convener_role,
):
    """The POST endpoint is a different view from the tab that renders the
    form — if their gates disagreed, the form would 403 on submit."""
    event, convener = _offering(event_type, convener_role)
    client.force_login(convener)
    resp = client.post(
        f"/events/{event.slug}/codes/",
        {"pricing_mode": PricingCode.Mode.FULL_PRICE, "installments": "3"},
    )
    assert resp.status_code == 302
    code = event.pricing_codes.get()
    assert code.installments == 3
    assert code.issued_by == convener


def test_a_plain_member_cannot_mint_a_code(client):
    event, _convener = _offering(Event.Type.READING_GROUP, "organizer")
    outsider = _user("outsider@example.com")
    client.force_login(outsider)
    resp = client.post(
        f"/events/{event.slug}/codes/",
        {"pricing_mode": PricingCode.Mode.FULL_PRICE, "installments": "3"},
    )
    assert resp.status_code == 403
    assert event.pricing_codes.count() == 0


# ---- The plan is disclosed before checkout -------------------------------


def test_redeeming_a_plan_code_lands_on_the_schedule_not_stripe(client, monkeypatch):
    """A member must see what they're committing to before paying. Redeeming a
    plan code used to bounce straight to Stripe asking for $166.66 when the
    event page said $500."""
    from registrations.models import Registration
    member = _user()
    issuer = _user("faculty@example.com")
    event = _dated_event(date(2026, 9, 1), date(2027, 5, 31))
    tier = _tier(event, "500.00")
    code = _code(event, issuer, installments=3)

    def _boom(installment):
        raise AssertionError("must not open Checkout before the member confirms")

    monkeypatch.setattr(
        "registrations.views.create_registration_installment_session", _boom,
    )

    client.force_login(member)
    resp = client.post(
        f"/events/{event.slug}/register/",
        {"price_tier": tier.pk, "pricing_code": code.code},
    )
    reg = Registration.objects.get(user=member, event=event)
    assert resp.status_code == 302
    assert resp["Location"] == f"/registrations/{reg.pk}/confirmation/"
    assert reg.status == Registration.Status.AWAITING_PAYMENT
    assert reg.installments.count() == 3


def test_the_schedule_page_offers_the_first_payment_not_the_whole_fee(client):
    """An unpaid plan registration must not also show the full-fee Pay button:
    two competing payment paths on one page, and the plan is the one the member
    agreed to."""
    from payments import registration_plans
    from registrations.models import Registration
    member = _user()
    event = _dated_event(date(2026, 9, 1), date(2027, 5, 31))
    tier = _tier(event)
    reg = _registration(
        member, event, tier, "500.00",
        status=Registration.Status.AWAITING_PAYMENT,
    )
    registration_plans.build_schedule(reg, 3, today=date(2026, 9, 1))

    client.force_login(member)
    body = client.get(f"/registrations/{reg.pk}/confirmation/").content.decode()
    assert "payment plan" in body.lower()
    assert "$166.66" in body                       # the first payment
    assert "Pay $500.00 →" not in body             # not the whole fee
    assert f"/registrations/{reg.pk}/pay/" not in body


def test_the_full_fee_endpoint_refuses_a_plan_registration(client):
    """Defence in depth: the button is gone, so a POST here is a stale form."""
    from payments import registration_plans
    from registrations.models import Registration
    member = _user()
    event = _dated_event(date(2026, 9, 1), date(2027, 5, 31))
    tier = _tier(event)
    reg = _registration(
        member, event, tier, "500.00",
        status=Registration.Status.AWAITING_PAYMENT,
    )
    registration_plans.build_schedule(reg, 3, today=date(2026, 9, 1))

    client.force_login(member)
    resp = client.post(f"/registrations/{reg.pk}/pay/")
    assert resp.status_code == 302
    assert resp["Location"] == f"/registrations/{reg.pk}/confirmation/"


def test_an_ordinary_registration_still_goes_straight_to_checkout(client, monkeypatch):
    from registrations.models import Registration
    member = _user()
    event = _dated_event(date(2026, 9, 1), date(2027, 5, 31))
    tier = _tier(event, "500.00")

    monkeypatch.setattr(
        "registrations.views.create_checkout_session",
        lambda reg: (None, type("S", (), {"url": "https://stripe.test/s"})()),
    )
    client.force_login(member)
    resp = client.post(
        f"/events/{event.slug}/register/", {"price_tier": tier.pk},
    )
    assert resp["Location"] == "https://stripe.test/s"
    assert Registration.objects.get(user=member, event=event).installments.count() == 0


# ---- Cancelling kills the open Checkout session --------------------------
#
# A cancelled registration used to leave its Stripe session live for the rest
# of its ~24h window. A member who cancelled and re-registered (the only way to
# apply a code to an existing registration) could then complete the stale tab
# and be charged for a place they already hold, with no Charge minted against
# it because the settle guard sees a non-settled registration.


def _pending_payment(reg, session_id="cs_test_open"):
    from payments.models import Payment
    return Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, registration=reg,
        user=reg.user, amount=reg.quoted_amount,
        method=Payment.Method.STRIPE, status=Payment.Status.PENDING,
        stripe_checkout_session_id=session_id,
    )


def test_cancelling_expires_the_open_checkout_session(monkeypatch):
    from payments.models import Payment
    from registrations.models import Registration
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier, "250.00")
    pay = _pending_payment(reg)

    expired = []
    monkeypatch.setattr(
        "payments.stripe_sync.stripe.checkout.Session.expire",
        lambda sid: expired.append(sid),
    )

    reg.cancel()
    reg.refresh_from_db()
    pay.refresh_from_db()
    assert reg.status == Registration.Status.CANCELLED
    assert expired == ["cs_test_open"]
    assert pay.status == Payment.Status.ABANDONED


def test_a_session_stripe_says_is_already_paid_is_left_alone(monkeypatch):
    """If Stripe refuses the expiry the money may really have arrived; leave
    the row PENDING for the nightly reconcile rather than calling it
    abandoned."""
    import stripe as _stripe

    from payments.models import Payment
    from registrations.models import Registration
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(member, event, tier, "250.00")
    pay = _pending_payment(reg)

    def _refuse(sid):
        raise _stripe.error.InvalidRequestError("already completed", None)

    monkeypatch.setattr(
        "payments.stripe_sync.stripe.checkout.Session.expire", _refuse,
    )

    reg.cancel()          # must not raise
    reg.refresh_from_db()
    pay.refresh_from_db()
    assert reg.status == Registration.Status.CANCELLED
    assert pay.status == Payment.Status.PENDING


def test_cancelling_leaves_settled_payments_alone(monkeypatch):
    from payments.models import Payment
    from registrations.models import Registration
    member = _user()
    event = _event()
    tier = _tier(event)
    reg = _registration(
        member, event, tier, "250.00", status=Registration.Status.PAID,
    )
    done = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, registration=reg, user=member,
        amount=Decimal("250.00"), method=Payment.Method.STRIPE,
        status=Payment.Status.SUCCEEDED, stripe_payment_intent_id="pi_ok",
        stripe_checkout_session_id="cs_done",
    )
    expired = []
    monkeypatch.setattr(
        "payments.stripe_sync.stripe.checkout.Session.expire",
        lambda sid: expired.append(sid),
    )
    monkeypatch.setattr(
        "payments.refund.refund_payment", lambda p: {"id": "re_x"},
    )

    reg.cancel()
    done.refresh_from_db()
    assert expired == []                       # nothing open to expire
    assert done.status == Payment.Status.SUCCEEDED


# ---- The roster shows active registrations only --------------------------


def test_the_roster_hides_cancelled_and_refunded(client):
    """Faculty were seeing their own test registrations, cancelled, sitting on
    the roster. The CSV already excluded them."""
    from registrations.models import Registration
    faculty = _user("faculty@example.com")
    faculty.profile.is_faculty = True
    faculty.profile.save()
    event = _event()
    event.add_faculty(faculty)
    tier = _tier(event)

    live = _registration(
        _user("live@example.com"), event, tier, "250.00",
        status=Registration.Status.PAID,
    )
    _registration(
        _user("gone@example.com"), event, tier, "250.00",
        status=Registration.Status.CANCELLED,
    )
    _registration(
        _user("back@example.com"), event, tier, "250.00",
        status=Registration.Status.REFUNDED,
    )

    client.force_login(faculty)
    body = client.get(
        event.workgroup.get_absolute_url() + "?tab=roster"
    ).content.decode()

    # Scoped to the roster's own cells: every account also appears in the
    # pricing-code form's "Only this person may use it" dropdown.
    def on_roster(email):
        return f'<td class="text-base-content/70">{email}</td>' in body

    assert on_roster(live.user.email)
    assert not on_roster("gone@example.com")
    assert not on_roster("back@example.com")


# ---- A code can be applied to a registration that already exists ---------
#
# Previously a code could only be redeemed on the register form, which an
# already-registered member is bounced past. The only route was cancel and
# re-register, i.e. give up your place to receive your scholarship.


def _apply(client, reg, code, **extra):
    return client.post(
        f"/registrations/{reg.pk}/apply-code/",
        {"pricing_code": code.code, **extra}, follow=True,
    )


def test_a_scholarship_code_settles_an_existing_registration(client):
    from events.models import PricingCode
    from registrations.models import Registration
    member = _user()
    issuer = _user("faculty@example.com")
    event = _event()
    tier = _tier(event, "250.00")
    reg = _registration(member, event, tier, "250.00")
    code = _code(
        event, issuer, pricing_mode=PricingCode.Mode.FIXED_AMOUNT,
        amount_or_percent=Decimal("0"), max_uses=1, restricted_to_user=member,
    )

    client.force_login(member)
    _apply(client, reg, code)

    reg.refresh_from_db()
    code.refresh_from_db()
    assert reg.status == Registration.Status.PAID
    assert reg.quoted_amount == Decimal("0.00")
    assert reg.pricing_code_id == code.pk
    assert code.uses_remaining == 0
    # The confirmation email itself goes out on transaction.on_commit, which
    # pytest-django doesn't run; the bell row is written synchronously.
    from notifications.models import Notification
    assert Notification.objects.filter(recipient=member).exists()


def test_a_discount_code_reprices_without_settling(client):
    from events.models import PricingCode
    from registrations.models import Registration
    member = _user()
    issuer = _user("faculty@example.com")
    event = _event()
    tier = _tier(event, "250.00")
    reg = _registration(member, event, tier, "250.00")
    code = _code(
        event, issuer, pricing_mode=PricingCode.Mode.PERCENT_OFF,
        amount_or_percent=Decimal("20"),
    )

    client.force_login(member)
    _apply(client, reg, code)

    reg.refresh_from_db()
    assert reg.quoted_amount == Decimal("200.00")
    assert reg.status == Registration.Status.AWAITING_PAYMENT


def test_applying_a_plan_code_builds_the_schedule(client):
    member = _user()
    issuer = _user("faculty@example.com")
    event = _dated_event(date(2026, 9, 1), date(2027, 5, 31))
    tier = _tier(event, "500.00")
    reg = _registration(member, event, tier, "500.00")
    code = _code(event, issuer, installments=3)

    client.force_login(member)
    _apply(client, reg, code)

    reg.refresh_from_db()
    assert reg.installments.count() == 3


def test_repricing_expires_the_stale_checkout(client, monkeypatch):
    """The old price must not remain payable from a tab left open."""
    from events.models import PricingCode
    from payments.models import Payment
    member = _user()
    issuer = _user("faculty@example.com")
    event = _event()
    tier = _tier(event, "250.00")
    reg = _registration(member, event, tier, "250.00")
    pay = _pending_payment(reg, "cs_stale")
    code = _code(
        event, issuer, pricing_mode=PricingCode.Mode.FIXED_AMOUNT,
        amount_or_percent=Decimal("0"),
    )
    expired = []
    monkeypatch.setattr(
        "payments.stripe_sync.stripe.checkout.Session.expire",
        lambda sid: expired.append(sid),
    )

    client.force_login(member)
    _apply(client, reg, code)

    pay.refresh_from_db()
    assert expired == ["cs_stale"]
    assert pay.status == Payment.Status.ABANDONED


def test_a_code_for_another_event_is_refused(client):
    from decimal import Decimal as D

    from registrations.models import Registration
    member = _user()
    issuer = _user("faculty@example.com")
    event = _event()
    other = _event(title="Other Seminar")
    tier = _tier(event, "250.00")
    reg = _registration(member, event, tier, "250.00")
    code = _code(other, issuer, pricing_mode="fixed_amount", amount_or_percent=D("0"))

    client.force_login(member)
    resp = _apply(client, reg, code)

    reg.refresh_from_db()
    assert reg.quoted_amount == D("250.00")
    assert reg.status == Registration.Status.AWAITING_PAYMENT
    assert "valid for this event" in resp.content.decode()


def test_a_code_pinned_to_someone_else_is_refused(client):
    from events.models import PricingCode
    member = _user()
    other = _user("other@example.com")
    issuer = _user("faculty@example.com")
    event = _event()
    tier = _tier(event, "250.00")
    reg = _registration(member, event, tier, "250.00")
    code = _code(
        event, issuer, pricing_mode=PricingCode.Mode.FIXED_AMOUNT,
        amount_or_percent=Decimal("0"), restricted_to_user=other,
    )

    client.force_login(member)
    _apply(client, reg, code)

    reg.refresh_from_db()
    assert reg.quoted_amount == Decimal("250.00")


def test_a_paid_registration_cannot_be_repriced(client):
    from events.models import PricingCode
    from registrations.models import Registration
    member = _user()
    issuer = _user("faculty@example.com")
    event = _event()
    tier = _tier(event, "250.00")
    reg = _registration(
        member, event, tier, "250.00", status=Registration.Status.PAID,
    )
    code = _code(
        event, issuer, pricing_mode=PricingCode.Mode.FIXED_AMOUNT,
        amount_or_percent=Decimal("0"),
    )

    client.force_login(member)
    _apply(client, reg, code)

    reg.refresh_from_db()
    assert reg.quoted_amount == Decimal("250.00")


def test_someone_elses_registration_is_404(client):
    from events.models import PricingCode
    member = _user()
    intruder = _user("intruder@example.com")
    issuer = _user("faculty@example.com")
    event = _event()
    tier = _tier(event, "250.00")
    reg = _registration(member, event, tier, "250.00")
    code = _code(
        event, issuer, pricing_mode=PricingCode.Mode.FIXED_AMOUNT,
        amount_or_percent=Decimal("0"),
    )
    client.force_login(intruder)
    resp = client.post(
        f"/registrations/{reg.pk}/apply-code/", {"pricing_code": code.code},
    )
    assert resp.status_code == 404


def test_the_confirmation_page_offers_the_code_box(client):
    member = _user()
    event = _event()
    tier = _tier(event, "250.00")
    reg = _registration(member, event, tier, "250.00")
    client.force_login(member)
    body = client.get(f"/registrations/{reg.pk}/confirmation/").content.decode()
    assert f"/registrations/{reg.pk}/apply-code/" in body
