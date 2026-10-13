"""Per-class billing: regressions for the whole-branch review (task #811)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone

from events import per_class
from events.forms import SessionScheduleFormSet
from events.models import ClassAttendance, EventChangeRequest, PricingCode
from events.per_class_fixtures import (
    enroll,
    make_event,
    make_session,
    make_tier,
    make_user,
)
from events.price_spec import PriceSpec
from notifications.models import Notification
from payments.charges import mint_registration_charge
from payments.models import Charge, Payment, TuitionEnrollment, TuitionPeriod
from registrations.models import Registration
from registrations.services import auto_apply_pinned_code

pytestmark = pytest.mark.django_db
HOUR = timedelta(hours=1)


def _bill_one(event, ends_ago=timedelta(days=5)):
    session = make_session(event, ends_ago=ends_ago)
    per_class.run(now=session.end_at + HOUR)
    per_class.run(now=session.end_at + per_class.WINDOW + HOUR)
    return session


# ---- 1: a seminar's balance is its own money ---------------------------------


def test_unrelated_registration_credit_does_not_pay_classes():
    event = make_event()
    user = make_user()
    reg = enroll(user, event, make_tier(event))
    # An imported registration payment with no charge: credit in the bucket.
    Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, user=user, amount=Decimal("100"),
        status=Payment.Status.SUCCEEDED,
    )
    _bill_one(event)
    assert per_class.open_balance(reg) == Decimal("25.00")
    att = ClassAttendance.objects.get()
    assert per_class.can_unbill(att)


def test_a_class_payment_pays_the_classes_not_an_older_seminar():
    user = make_user()
    other = make_event("Older Seminar", per_class=False)
    other_tier = make_tier(other, amount="300")
    older = enroll(user, other, other_tier, rate=None)
    Charge.objects.create(
        user=user, category="registration", amount=Decimal("300"),
        effective_date=timezone.localdate() - timedelta(days=60), registration=older,
    )
    event = make_event()
    reg = enroll(user, event, make_tier(event))
    _bill_one(event)
    Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, per_class_registration=reg,
        user=user, amount=Decimal("25"), status=Payment.Status.SUCCEEDED,
    )
    assert per_class.open_balance(reg) == Decimal("0")


# ---- 2: a refund doesn't drop a per-class place --------------------------------


def _converted_with_payment():
    event = make_event()
    user = make_user()
    reg = enroll(user, event, make_tier(event))
    pay = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, registration=reg, user=user,
        amount=Decimal("25"), status=Payment.Status.SUCCEEDED,
        method=Payment.Method.STRIPE, stripe_payment_intent_id="pi_conv",
    )
    return reg, pay


def test_stripe_refund_keeps_a_per_class_registration_enrolled(client):
    reg, pay = _converted_with_payment()
    payload = {"id": "evt_r", "type": "charge.refunded",
               "data": {"object": {"payment_intent": "pi_conv"}}}
    with patch("payments.views.stripe.Webhook.construct_event", return_value=payload):
        client.post(reverse("payments:stripe_webhook"), data=b"{}",
                    content_type="application/json", HTTP_STRIPE_SIGNATURE="t=1,v1=x")
    pay.refresh_from_db()
    reg.refresh_from_db()
    assert pay.status == Payment.Status.REFUNDED
    assert reg.status == Registration.Status.PAID


# ---- 3: no whole-seminar charge re-minted -----------------------------------


def test_mint_registration_charge_skips_a_per_class_registration():
    reg, pay = _converted_with_payment()
    assert mint_registration_charge(pay) is None
    assert not Charge.objects.filter(registration=reg).exists()


# ---- 4: the lock refuses cleanly ------------------------------------------------


def test_edit_form_refuses_a_mode_change_with_registrants():
    from events.forms import EventEditForm

    event = make_event(per_class=False)
    tier = make_tier(event, amount="300")
    enroll(make_user(), event, tier, rate=None)
    form = EventEditForm(instance=event)
    data = {k: v for k, v in form.initial.items() if v is not None}
    data.update({"fee_type": "fixed", "fee_amount": "25",
                 "billing_mode": "per_class", "title": event.title})
    bound = EventEditForm(data=data, instance=event)
    assert not bound.is_valid()
    assert "billing_mode" in bound.errors


def test_a_change_request_applied_after_registrations_keeps_the_mode():
    event = make_event(per_class=False)
    tier = make_tier(event, amount="300")
    enroll(make_user(), event, tier, rate=None)
    cr = EventChangeRequest(
        event=event, changed_fields=["price"],
        proposed_price=PriceSpec(amount=Decimal("280"), tuition_covers=False,
                                 per_class=True).to_dict(),
    )
    cr.apply()
    event.refresh_from_db()
    tier.refresh_from_db()
    assert not event.is_per_class
    assert tier.base_amount == Decimal("280")


def test_a_free_price_is_never_per_class():
    from events.forms import PriceFieldsMixin

    form = PriceFieldsMixin()
    form._price_event = None
    data = form.clean_price({"fee_type": "free", "billing_mode": "per_class"})
    assert data["price"].per_class is False


# ---- 5: a billed class can't be deleted from the schedule -------------------------


def test_schedule_editor_refuses_deleting_a_billed_class():
    event = make_event()
    enroll(make_user(), event, make_tier(event))
    session = _bill_one(event)
    prefix = "sessions"
    local = timezone.localtime(session.start_at)
    data = {
        f"{prefix}-TOTAL_FORMS": "1", f"{prefix}-INITIAL_FORMS": "1",
        f"{prefix}-MIN_NUM_FORMS": "0", f"{prefix}-MAX_NUM_FORMS": "1000",
        f"{prefix}-0-id": str(session.pk), f"{prefix}-0-event": str(event.pk),
        f"{prefix}-0-DELETE": "on",
        f"{prefix}-0-start_at": local.strftime("%Y-%m-%dT%H:%M"),
        f"{prefix}-0-end_at": timezone.localtime(session.end_at).strftime("%Y-%m-%dT%H:%M"),
    }
    formset = SessionScheduleFormSet(data, instance=event, prefix=prefix)
    assert not formset.is_valid()
    assert "billed" in " ".join(formset.non_form_errors())


# ---- 6: a pinned code doesn't end tuition coverage ------------------------------


def test_pinned_code_is_not_applied_to_a_covered_member():
    today = timezone.localdate()
    TuitionPeriod.objects.all().delete()
    period = TuitionPeriod.objects.create(
        name="AY rv", slug="ay-rv", start_date=today - timedelta(days=100),
        decision_due_date=today, end_date=today + timedelta(days=200),
        tuition_amount=Decimal("800"),
    )
    user = make_user()
    TuitionEnrollment.objects.create(user=user, tuition_period=period, status="committed")
    event = make_event()
    reg = enroll(user, event, make_tier(event, covered_by_tuition=True))
    PricingCode.objects.create(
        event=event, issued_by=make_user("f@example.com"),
        pricing_mode=PricingCode.Mode.FIXED_AMOUNT, amount_or_percent=Decimal("5"),
        restricted_to_user=user,
    )
    assert auto_apply_pinned_code(reg) is None
    reg.refresh_from_db()
    assert reg.pricing_code_id is None


# ---- 7: detection judges each person's time in the room -------------------------


def test_detection_uses_each_participants_time_in_the_room(settings):
    from video.models import DailyRoom
    from video.services import _room_name, room_owner_for_event

    settings.DAILY_ENABLED = True
    settings.DAILY_API_KEY = "k"
    settings.DAILY_DOMAIN = "x.daily.co"
    from events.models import Event

    event = make_event(format=Event.Format.ONLINE, online_venue=Event.OnlineVenue.INSITE)
    owner = room_owner_for_event(event, create=True)
    DailyRoom.objects.create(workgroup=owner, name=_room_name(owner), url="https://x/r")
    tier = make_tier(event)
    during = make_user("during@example.com")
    before = make_user("before@example.com")
    enroll(during, event, tier)
    enroll(before, event, tier)
    session = make_session(event)
    start = int(session.start_at.timestamp())
    meetings = [{"id": "long", "participants": [
        {"user_id": str(during.pk), "join_time": start + 600, "duration": 3000},
        {"user_id": str(before.pk), "join_time": start - 4 * 3600, "duration": 600},
    ]}]
    with patch("video.daily.list_meetings", return_value=meetings) as lookup:
        per_class.run()
    assert lookup.call_args.kwargs["start"] < start - 3600 * 6
    rows = {a.registration.user_id: a.present for a in ClassAttendance.objects.all()}
    assert rows == {during.pk: True, before.pk: False}


# ---- 8: one bad row doesn't stall billing ----------------------------------------


def test_a_failing_row_does_not_stop_the_others():
    event = make_event()
    tier = make_tier(event)
    enroll(make_user("a@example.com"), event, tier)
    enroll(make_user("b@example.com"), event, tier)
    session = make_session(event, ends_ago=timedelta(days=5))
    per_class.run(now=session.end_at + HOUR)
    real = per_class._mint
    calls = {"n": 0}

    def flaky(att, amount, *, source):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real(att, amount, source=source)

    with patch("events.per_class._mint", side_effect=flaky):
        stats = per_class.run(now=session.end_at + per_class.WINDOW + HOUR)
    assert stats["errors"] == 1
    assert Charge.objects.count() == 1


# ---- 9: the weekly note -------------------------------------------------------------


def test_weekly_note_once_a_week_and_totals_the_charges():
    from datetime import datetime, time

    event = make_event()
    user = make_user()
    reg = enroll(user, event, make_tier(event))
    today = timezone.localdate()
    monday = timezone.make_aware(datetime.combine(
        today - timedelta(days=today.weekday()), time(10)))
    _bill_one(event, ends_ago=timezone.now() - (monday - timedelta(days=6)))
    reg.per_class_rate = Decimal("99")
    reg.save()
    per_class.send_billing_notices(monday)
    note = Notification.objects.get(recipient=user, category="class_billing")
    assert "$25.00" in note.body
    # A class billed later the same Monday waits for next week.
    att = ClassAttendance.objects.get()
    ClassAttendance.objects.filter(pk=att.pk).update(notified_at=None)
    ClassAttendance.objects.create(
        registration=reg, session=make_session(event, ends_ago=timedelta(days=9)),
        source="presumed", outcome="charged", billed_at=monday,
    )
    ClassAttendance.objects.filter(pk=att.pk).update(notified_at=monday)
    per_class.send_billing_notices(monday + HOUR)
    assert Notification.objects.filter(category="class_billing").count() == 1
