"""Per-class billing pipeline: record, correct, bill, notify (task #811)."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from events import per_class
from events.models import ClassAttendance, Event
from events.per_class_fixtures import (
    enroll,
    local_session,
    make_event,
    make_session,
    make_tier,
    make_user,
)
from notifications.models import Notification
from payments.models import Charge, Payment, TuitionEnrollment, TuitionPeriod
from registrations.models import Registration

pytestmark = pytest.mark.django_db

HOUR = timedelta(hours=1)


@pytest.fixture
def seminar():
    event = make_event()
    tier = make_tier(event)
    return event, tier


def _past_window(session):
    return session.end_at + per_class.WINDOW + HOUR


def _record_and_bill(session, now=None):
    per_class.run(now=session.end_at + HOUR)
    return per_class.run(now=now or _past_window(session))


# ---- recording -----------------------------------------------------------------


def test_in_person_class_presumes_everyone_present(seminar):
    event, tier = seminar
    a = enroll(make_user("a@example.com"), event, tier)
    b = enroll(make_user("b@example.com"), event, tier)
    session = make_session(event, ends_ago=timedelta(minutes=30))
    per_class.run()
    rows = ClassAttendance.objects.filter(session=session)
    assert {r.registration_id for r in rows} == {a.id, b.id}
    assert all(r.present and r.source == "presumed" for r in rows)


def test_a_class_is_not_recorded_until_shortly_after_it_ends(seminar):
    event, tier = seminar
    enroll(make_user(), event, tier)
    make_session(event, ends_ago=timedelta(minutes=5))
    per_class.run()
    assert not ClassAttendance.objects.exists()


def test_late_registrant_is_not_recorded_for_earlier_classes(seminar):
    """Review focus 5."""
    event, tier = seminar
    enroll(make_user(), event, tier, created_ago=timedelta(minutes=10))
    make_session(event, ends_ago=timedelta(hours=1))
    per_class.run()
    assert not ClassAttendance.objects.exists()


def test_classes_before_the_event_became_per_class_are_not_recorded(seminar):
    event, tier = seminar
    enroll(make_user(), event, tier)
    make_session(event, ends_ago=timedelta(days=3))
    Event.objects.filter(pk=event.pk).update(per_class_since=timezone.now() - timedelta(days=1))
    per_class.run()
    assert not ClassAttendance.objects.exists()


def test_whole_seminar_events_are_untouched():
    event = make_event(per_class=False)
    tier = make_tier(event, amount="300")
    enroll(make_user(), event, tier, rate=None)
    make_session(event)
    per_class.run()
    assert not ClassAttendance.objects.exists()


def test_cancelled_and_pending_registrants_are_not_recorded(seminar):
    event, tier = seminar
    enroll(make_user("c@example.com"), event, tier, status=Registration.Status.CANCELLED)
    enroll(make_user("p@example.com"), event, tier, status=Registration.Status.PENDING_APPROVAL)
    make_session(event)
    per_class.run()
    assert not ClassAttendance.objects.exists()


def test_recording_notifies_leads_and_registrants(seminar):
    event, tier = seminar
    user = make_user()
    enroll(user, event, tier)
    make_session(event)
    with patch("events.permissions.offering_leads", return_value=[make_user("lead@example.com")]):
        per_class.run()
    assert Notification.objects.filter(recipient=user, category="class_attendance").exists()
    assert Notification.objects.filter(
        recipient__email="lead@example.com", category="class_attendance",
    ).exists()


# ---- detection -------------------------------------------------------------------


@pytest.fixture
def online_seminar(settings):
    settings.DAILY_ENABLED = True
    settings.DAILY_API_KEY = "k"
    settings.DAILY_DOMAIN = "lsp.daily.co"
    event = make_event(
        format=Event.Format.ONLINE, online_venue=Event.OnlineVenue.INSITE,
    )
    tier = make_tier(event)
    from video.models import DailyRoom
    from video.services import _room_name, room_owner_for_event

    owner = room_owner_for_event(event, create=True)
    DailyRoom.objects.create(
        workgroup=owner, name=_room_name(owner), url="https://x.test/r",
    )
    return event, tier


def test_room_joins_decide_attendance(online_seminar):
    event, tier = online_seminar
    came = make_user("came@example.com")
    missed = make_user("missed@example.com")
    enroll(came, event, tier)
    enroll(missed, event, tier)
    make_session(event)
    meetings = [{"id": "m1", "participants": [
        {"user_id": str(came.pk)}, {"user_id": None, "user_name": "Guest"},
    ]}]
    with patch("video.daily.list_meetings", return_value=meetings):
        per_class.run()
    rows = {r.registration.user_id: r for r in ClassAttendance.objects.all()}
    assert rows[came.pk].present and rows[came.pk].source == "detected"
    assert not rows[missed.pk].present


def test_unreadable_room_retries_then_presumes(online_seminar):
    event, tier = online_seminar
    enroll(make_user(), event, tier)
    session = make_session(event)
    from video.daily import DailyError

    with patch("video.daily.list_meetings", side_effect=DailyError("down")):
        stats = per_class.run(now=session.end_at + HOUR)
        assert stats["retry"] == 1
        assert not ClassAttendance.objects.exists()
        per_class.run(now=session.end_at + per_class.DETECT_RETRY + HOUR)
    att = ClassAttendance.objects.get()
    assert att.present and att.source == "presumed"
    assert "couldn't be read" in att.notes


def test_hybrid_class_is_presumed_not_detected(online_seminar):
    event, tier = online_seminar
    Event.objects.filter(pk=event.pk).update(format=Event.Format.HYBRID)
    enroll(make_user(), event, tier)
    make_session(event)
    with patch("video.daily.list_meetings") as lookup:
        per_class.run()
    lookup.assert_not_called()
    assert ClassAttendance.objects.get().source == "presumed"


def test_room_tokens_carry_the_member_id():
    from video.models import DailyRoom
    from video.services import mint_token

    user = make_user()
    room = DailyRoom(name="lsp-x", url="https://x.test/r")
    with patch("video.daily.create_meeting_token", return_value="t") as create:
        mint_token(room, user)
    assert create.call_args.kwargs["user_id"] == str(user.pk)


# ---- billing ---------------------------------------------------------------------


def test_no_bill_inside_the_window(seminar):
    event, tier = seminar
    enroll(make_user(), event, tier)
    session = make_session(event)
    per_class.run(now=session.end_at + HOUR)
    per_class.run(now=session.end_at + per_class.WINDOW - HOUR)
    assert not Charge.objects.exists()


def test_present_class_bills_one_registration_charge(seminar):
    event, tier = seminar
    user = make_user()
    reg = enroll(user, event, tier)
    session = make_session(event)
    _record_and_bill(session)
    charge = Charge.objects.get()
    assert charge.category == Charge.Category.REGISTRATION
    assert charge.amount == Decimal("25.00")
    assert charge.registration_id is None
    assert charge.class_attendance.registration == reg
    assert ClassAttendance.objects.get().outcome == "charged"


def test_billing_twice_mints_once(seminar):
    """Review focus 3."""
    event, tier = seminar
    enroll(make_user(), event, tier)
    session = make_session(event)
    _record_and_bill(session)
    per_class.run(now=_past_window(session) + HOUR)
    att = ClassAttendance.objects.get()
    assert per_class.bill(att) is not None
    assert Charge.objects.count() == 1


def test_charge_is_dated_the_school_local_class_day(seminar):
    """Review focus 4: a 17:30 Pacific class is already tomorrow in UTC."""
    event, tier = seminar
    enroll(make_user(), event, tier)
    day = timezone.localdate() - timedelta(days=5)
    session = local_session(event, day, start=time(17, 30))
    _record_and_bill(session)
    assert Charge.objects.get().effective_date == day


def test_absent_comped_and_free_rows_bill_nothing(seminar):
    event, tier = seminar
    absent = enroll(make_user("absent@example.com"), event, tier)
    comped = enroll(make_user("comped@example.com"), event, tier, status=Registration.Status.COMPED)
    free = enroll(make_user("free@example.com"), event, tier, rate="0")
    session = make_session(event)
    per_class.run(now=session.end_at + HOUR)
    ClassAttendance.objects.filter(registration=absent).update(present=False)
    per_class.run(now=_past_window(session))
    assert not Charge.objects.exists()
    outcomes = {a.registration_id: a.outcome for a in ClassAttendance.objects.all()}
    assert outcomes == {absent.id: "absent", comped.id: "comped", free.id: "no_charge"}


def test_registrant_who_cancelled_mid_window_still_pays_for_the_class(seminar):
    event, tier = seminar
    reg = enroll(make_user(), event, tier)
    session = make_session(event)
    per_class.run(now=session.end_at + HOUR)
    reg.cancel()
    per_class.run(now=_past_window(session))
    assert Charge.objects.count() == 1


# ---- balances ---------------------------------------------------------------------


def test_existing_registration_credit_pays_the_first_class(seminar):
    """The #810 shape: a $25 whole-seminar payment whose charge was voided."""
    event, tier = seminar
    user = make_user()
    reg = enroll(user, event, tier)
    Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, registration=reg, user=user,
        amount=Decimal("25"), status=Payment.Status.SUCCEEDED,
    )
    for days in (3, 10):
        make_session(event, ends_ago=timedelta(days=days))
    per_class.run(now=timezone.now() - timedelta(days=9))
    per_class.run(now=timezone.now() - timedelta(days=2))
    per_class.run()
    assert Charge.objects.count() == 2
    assert per_class.open_balance(reg) == Decimal("25.00")


# ---- corrections --------------------------------------------------------------------


def _recorded(seminar, **kw):
    event, tier = seminar
    user = make_user()
    reg = enroll(user, event, tier, **kw)
    session = make_session(event)
    per_class.run(now=session.end_at + HOUR)
    return user, reg, session, ClassAttendance.objects.get()


def test_member_marks_themselves_absent_in_the_window(seminar):
    user, reg, session, att = _recorded(seminar)
    per_class.mark(att, present=False, by=user, as_faculty=False)
    per_class.run(now=_past_window(session))
    assert not Charge.objects.exists()


def test_faculty_mark_locks_the_member_out(seminar):
    user, reg, session, att = _recorded(seminar)
    faculty = make_user("faculty@example.com")
    per_class.mark(att, present=False, by=faculty, as_faculty=True)
    with pytest.raises(per_class.AttendanceError):
        per_class.mark(att, present=True, by=user, as_faculty=False)


def test_member_cannot_change_after_billing(seminar):
    user, reg, session, att = _recorded(seminar)
    per_class.run(now=_past_window(session))
    att.refresh_from_db()
    with pytest.raises(per_class.AttendanceError):
        per_class.mark(att, present=False, by=user, as_faculty=False)


def test_faculty_unbill_an_unpaid_class(seminar):
    user, reg, session, att = _recorded(seminar)
    per_class.run(now=_past_window(session))
    att.refresh_from_db()
    per_class.mark(att, present=False, by=make_user("f@example.com"), as_faculty=True)
    assert Charge.objects.get().status == Charge.Status.VOID
    att.refresh_from_db()
    assert att.outcome == "absent"
    assert Notification.objects.filter(recipient=user, category="class_billing").exists()


def test_faculty_cannot_unbill_a_paid_class(seminar):
    user, reg, session, att = _recorded(seminar)
    per_class.run(now=_past_window(session))
    Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, per_class_registration=reg,
        user=user, amount=Decimal("25"), status=Payment.Status.SUCCEEDED,
    )
    att.refresh_from_db()
    assert not per_class.can_unbill(att)
    with pytest.raises(per_class.AttendanceError):
        per_class.mark(att, present=False, by=make_user("f@example.com"), as_faculty=True)
    assert Charge.objects.get().status == Charge.Status.OPEN


def test_correction_closes_after_fourteen_days(seminar):
    user, reg, session, att = _recorded(seminar)
    billed = _past_window(session)
    per_class.run(now=billed)
    att.refresh_from_db()
    later = billed + timedelta(days=per_class.CORRECTION_DAYS, hours=1)
    with pytest.raises(per_class.AttendanceError):
        per_class.mark(att, present=False, by=make_user("f@example.com"),
                       as_faculty=True, now=later)


def test_faculty_marks_present_after_billing_bills_it(seminar):
    user, reg, session, att = _recorded(seminar)
    per_class.mark(att, present=False, by=user, as_faculty=False)
    per_class.run(now=_past_window(session))
    att.refresh_from_db()
    assert att.outcome == "absent"
    per_class.mark(att, present=True, by=make_user("f@example.com"), as_faculty=True)
    assert Charge.objects.get().status == Charge.Status.OPEN


# ---- tuition coverage ---------------------------------------------------------------


@pytest.fixture
def period():
    TuitionPeriod.objects.all().delete()
    today = timezone.localdate()
    return TuitionPeriod.objects.create(
        name="AY pc", slug="ay-pc", start_date=today - timedelta(days=200),
        decision_due_date=today, end_date=today + timedelta(days=200),
        tuition_amount=Decimal("800"),
    )


def _covered_seminar():
    event = make_event()
    tier = make_tier(event, covered_by_tuition=True)
    return event, tier


def test_covered_member_classes_are_not_charged(period):
    event, tier = _covered_seminar()
    user = make_user()
    TuitionEnrollment.objects.create(user=user, tuition_period=period, status="committed")
    enroll(user, event, tier)
    session = make_session(event)
    _record_and_bill(session)
    assert not Charge.objects.exists()
    assert ClassAttendance.objects.get().outcome == "covered"


def test_skipping_bills_covered_classes_and_committing_voids_them(period):
    event, tier = _covered_seminar()
    user = make_user()
    enr = TuitionEnrollment.objects.create(user=user, tuition_period=period, status="committed")
    enroll(user, event, tier)
    _record_and_bill(make_session(event))
    enr.status = TuitionEnrollment.Status.SKIPPING
    enr.save()
    assert len(per_class.covered_classes(user, period)) == 1
    billed = per_class.bill_covered_classes(user, period)
    assert len(billed) == 1 and billed[0].status == Charge.Status.OPEN
    enr.status = TuitionEnrollment.Status.COMMITTED
    enr.save()
    voided = per_class.void_covered_open(user, period)
    assert [c.pk for c in voided] == [billed[0].pk]
    assert Charge.objects.get().status == Charge.Status.VOID


def test_treasurer_skipping_never_bills_classes(period, client):
    event, tier = _covered_seminar()
    user = make_user()
    TuitionEnrollment.objects.create(user=user, tuition_period=period, status="committed")
    enroll(user, event, tier)
    _record_and_bill(make_session(event))
    staff = make_user("staff@example.com")
    staff.is_staff = True
    staff.save()
    client.force_login(staff)
    from django.urls import reverse

    client.post(
        reverse("treasurer_tuition_set_status", args=[user.pk]),
        {"status": "skipping", "period": period.pk},
    )
    assert TuitionEnrollment.objects.get(user=user).status == "skipping"
    assert not Charge.objects.exists()


# ---- weekly notes ------------------------------------------------------------------


def _monday(hour):
    today = timezone.localdate()
    monday = today - timedelta(days=today.weekday())
    return timezone.make_aware(datetime.combine(monday, time(hour, 0)))


def test_billing_notes_go_out_monday_morning_once(seminar):
    event, tier = seminar
    user = make_user()
    enroll(user, event, tier, created_ago=timedelta(days=60))
    monday = _monday(10)
    session = local_session(event, (monday - timedelta(days=6)).date(), start=time(10))
    per_class.run(now=session.end_at + HOUR)
    per_class.run(now=_past_window(session))
    assert not Notification.objects.filter(category="class_billing").exists()
    per_class.run(now=_monday(8))
    assert not Notification.objects.filter(category="class_billing").exists()
    per_class.run(now=monday)
    per_class.run(now=monday + HOUR)
    assert Notification.objects.filter(recipient=user, category="class_billing").count() == 1


def test_the_reminders_command_runs_the_pass(seminar):
    event, tier = seminar
    enroll(make_user(), event, tier)
    make_session(event)
    call_command("send_meeting_reminders")
    assert ClassAttendance.objects.exists()
