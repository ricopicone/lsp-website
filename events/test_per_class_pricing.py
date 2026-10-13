"""Per-class billing: schema, the price spec and codes (task #811)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.db.models.deletion import ProtectedError

from events.forms import PricingCodeForm
from events.models import ClassAttendance, Event, PricingCode
from events.per_class_fixtures import (
    enroll,
    make_event,
    make_session,
    make_tier,
    make_user,
)
from events.price_spec import (
    BillingModeLocked,
    PriceSpec,
    apply_to_event,
    from_event,
    label,
)
from payments.models import Charge
from registrations.models import Registration

pytestmark = pytest.mark.django_db


# ---- schema ---------------------------------------------------------------


def test_events_default_to_whole_seminar_billing():
    assert Event._meta.get_field("billing_mode").default == Event.BillingMode.WHOLE
    assert not make_event("Plain", per_class=False).is_per_class


def test_registration_is_per_class_when_it_carries_a_rate():
    event = make_event()
    tier = make_tier(event)
    reg = enroll(make_user(), event, tier)
    assert reg.is_per_class
    reg.per_class_rate = None
    assert not reg.is_per_class


def test_a_void_class_charge_does_not_block_a_new_one():
    event = make_event()
    tier = make_tier(event)
    user = make_user()
    reg = enroll(user, event, tier)
    att = ClassAttendance.objects.create(
        registration=reg, session=make_session(event), source="presumed",
    )
    first = Charge.objects.create(
        user=user, category="registration", amount=Decimal("25"),
        effective_date="2026-10-01", class_attendance=att, status="void",
    )
    second = Charge.objects.create(
        user=user, category="registration", amount=Decimal("25"),
        effective_date="2026-10-01", class_attendance=att,
    )
    assert first.pk != second.pk


def test_a_billed_class_protects_its_session_from_deletion():
    event = make_event()
    tier = make_tier(event)
    user = make_user()
    reg = enroll(user, event, tier)
    session = make_session(event)
    att = ClassAttendance.objects.create(
        registration=reg, session=session, source="presumed",
    )
    Charge.objects.create(
        user=user, category="registration", amount=Decimal("25"),
        effective_date="2026-10-01", class_attendance=att,
    )
    with pytest.raises(ProtectedError):
        session.delete()


def test_unbilled_attendance_deletes_with_its_session():
    event = make_event()
    reg = enroll(make_user(), event, make_tier(event))
    session = make_session(event)
    ClassAttendance.objects.create(registration=reg, session=session, source="presumed")
    session.delete()
    assert not ClassAttendance.objects.exists()


# ---- the price spec ---------------------------------------------------------


def test_spec_round_trips_per_class():
    spec = PriceSpec(amount=Decimal("25"), tuition_covers=False, per_class=True)
    assert PriceSpec.from_dict(spec.to_dict()) == spec


def test_a_spec_dict_from_before_the_feature_reads_whole_seminar():
    assert PriceSpec.from_dict({"amount": "25"}).per_class is False


def test_label_says_per_class():
    fixed = PriceSpec(amount=Decimal("25"), tuition_covers=False, per_class=True)
    assert label(fixed) == "$25 per class"
    assert label(PriceSpec(
        sliding_min=Decimal("10"), sliding_max=Decimal("40"),
        tuition_covers=True, per_class=True,
    )) == "Sliding scale $10 to $40 per class, covered by School tuition"


def test_from_event_reads_the_mode():
    event = make_event()
    make_tier(event)
    assert from_event(event).per_class is True


def test_apply_sets_the_mode_when_nobody_is_registered():
    event = make_event(per_class=False)
    make_tier(event, amount="300")
    apply_to_event(event, PriceSpec(amount=Decimal("25"), tuition_covers=False, per_class=True))
    event.refresh_from_db()
    assert event.is_per_class


def test_mode_locks_once_anyone_is_registered():
    event = make_event(per_class=False)
    tier = make_tier(event, amount="300")
    enroll(make_user(), event, tier, rate=None)
    with pytest.raises(BillingModeLocked):
        apply_to_event(event, PriceSpec(amount=Decimal("25"), tuition_covers=False, per_class=True))
    event.refresh_from_db()
    assert not event.is_per_class


def test_a_cancelled_registration_does_not_lock_the_mode():
    event = make_event(per_class=False)
    tier = make_tier(event, amount="300")
    enroll(make_user(), event, tier, rate=None, status=Registration.Status.CANCELLED)
    apply_to_event(event, PriceSpec(amount=Decimal("25"), tuition_covers=False, per_class=True))
    event.refresh_from_db()
    assert event.is_per_class


def test_a_price_change_that_keeps_the_mode_is_not_locked():
    event = make_event()
    tier = make_tier(event)
    enroll(make_user(), event, tier)
    apply_to_event(event, PriceSpec(amount=Decimal("30"), tuition_covers=False, per_class=True))
    tier.refresh_from_db()
    assert tier.base_amount == Decimal("30")


def test_proposal_approval_mints_per_class():
    from events.models import EventProposal

    proposer = make_user("faculty@example.com")
    pc = make_user("pc@example.com")
    proposal = EventProposal.objects.create(
        proposed_by=proposer, event_type=Event.Type.SEMINAR,
        title="Per Class Proposal", description="x",
        start_date=date(2026, 9, 1), end_date=date(2027, 5, 1),
        fee_amount=Decimal("25"), tuition_covers=False,
        billing_mode=Event.BillingMode.PER_CLASS,
    )
    event = proposal.approve(pc)
    event.refresh_from_db()
    assert event.is_per_class
    assert event.price_tiers.get().base_amount == Decimal("25")


# ---- codes ------------------------------------------------------------------


def _code_form(event, **data):
    data.setdefault("pricing_mode", PricingCode.Mode.FIXED_AMOUNT)
    data.setdefault("amount_or_percent", "10")
    return PricingCodeForm(data=data, event=event)


def test_per_class_code_refuses_installments():
    form = _code_form(make_event(), installments="3")
    assert not form.is_valid()
    assert "installments" in form.errors


def test_per_class_code_refuses_full_price():
    form = _code_form(make_event(), pricing_mode=PricingCode.Mode.FULL_PRICE)
    assert not form.is_valid()
    assert "pricing_mode" in form.errors


def test_per_class_code_accepts_a_fixed_rate():
    assert _code_form(make_event()).is_valid()


def test_whole_seminar_code_still_takes_installments():
    form = _code_form(make_event(per_class=False), installments="3")
    assert form.is_valid(), form.errors
