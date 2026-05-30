"""Tests for the tuition lifecycle (M7.5)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, User
from payments.models import TuitionEnrollment, TuitionInstallment, TuitionPeriod


@pytest.fixture
def current_period(db):
    """The current TuitionPeriod (created by the seed data migration).

    Falls back to a synthesized period covering today if the seed picked
    a future-only AY (running just before Sep 1).
    """
    period = TuitionPeriod.current()
    if period is not None:
        return period
    today = timezone.now().date()
    return TuitionPeriod.objects.create(
        name="Test AY",
        slug="test-ay-tuition",
        start_date=today - timedelta(days=60),
        decision_due_date=today + timedelta(days=30),
        end_date=today + timedelta(days=300),
        tuition_amount=Decimal("800.00"),
    )


def _mk_candidate(email="cand@example.com", *, role=Profile.Role.CANDIDATE):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = role
    u.profile.save()
    return u


# --- Models -------------------------------------------------------------


@pytest.mark.django_db
def test_owes_tuition_only_for_in_training_roles():
    for role in (
        Profile.Role.PRE_CANDIDATE, Profile.Role.CANDIDATE,
        Profile.Role.PRE_CANDIDATE_SCHOLAR, Profile.Role.CANDIDATE_SCHOLAR,
    ):
        u = _mk_candidate(email=f"{role}@x.test", role=role)
        assert u.profile.owes_tuition

    for role in (Profile.Role.ANALYST, Profile.Role.SCHOLAR, Profile.Role.MEMBER):
        u = _mk_candidate(email=f"{role}@x.test", role=role)
        assert not u.profile.owes_tuition


@pytest.mark.django_db
def test_is_tuition_current_requires_enrollment(current_period):
    u = _mk_candidate()
    assert u.profile.is_tuition_current() is False  # no enrollment

    TuitionEnrollment.objects.create(
        user=u, tuition_period=current_period,
        status=TuitionEnrollment.Status.COMMITTED,
    )
    # Re-fetch profile to clear any cached state from .profile access
    assert u.profile.is_tuition_current() is True


@pytest.mark.django_db
def test_skipping_status_is_not_tuition_current(current_period):
    u = _mk_candidate()
    TuitionEnrollment.objects.create(
        user=u, tuition_period=current_period,
        status=TuitionEnrollment.Status.SKIPPING,
    )
    assert u.profile.is_tuition_current() is False


@pytest.mark.django_db
def test_payment_plan_status_is_tuition_current(current_period):
    u = _mk_candidate()
    TuitionEnrollment.objects.create(
        user=u, tuition_period=current_period,
        status=TuitionEnrollment.Status.PAYMENT_PLAN,
    )
    assert u.profile.is_tuition_current() is True


@pytest.mark.django_db
def test_enrollment_unique_per_user_per_period(current_period):
    u = _mk_candidate()
    TuitionEnrollment.objects.create(
        user=u, tuition_period=current_period,
        status=TuitionEnrollment.Status.COMMITTED,
    )
    from django.db import IntegrityError
    with pytest.raises(IntegrityError):
        TuitionEnrollment.objects.create(
            user=u, tuition_period=current_period,
            status=TuitionEnrollment.Status.SKIPPING,
        )


@pytest.mark.django_db
def test_installment_mark_paid_is_idempotent(current_period):
    u = _mk_candidate()
    enr = TuitionEnrollment.objects.create(
        user=u, tuition_period=current_period,
        status=TuitionEnrollment.Status.PAYMENT_PLAN,
    )
    inst = TuitionInstallment.objects.create(
        enrollment=enr, sequence=1, due_date=date(2026, 10, 1),
        amount=Decimal("400.00"),
    )
    inst.mark_paid()
    first_paid_at = inst.paid_at
    assert inst.paid is True
    assert first_paid_at is not None

    inst.mark_paid()  # idempotent
    inst.refresh_from_db()
    assert inst.paid_at == first_paid_at


# --- Decision view ------------------------------------------------------


@pytest.mark.django_db
def test_tuition_view_requires_login(client):
    resp = client.get(reverse("tuition"))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.url


@pytest.mark.django_db
def test_tuition_view_renders_for_in_training_student(client, current_period):
    u = _mk_candidate()
    client.force_login(u)
    resp = client.get(reverse("tuition"))
    assert resp.status_code == 200
    assert current_period.name.encode() in resp.content
    assert b"Your decision" in resp.content


@pytest.mark.django_db
def test_tuition_view_explains_when_role_not_in_training(client):
    u = _mk_candidate(email="analyst@x.test", role=Profile.Role.ANALYST)
    client.force_login(u)
    resp = client.get(reverse("tuition"))
    assert resp.status_code == 200
    assert b"Analyst" in resp.content


@pytest.mark.django_db
def test_post_committed_creates_enrollment(client, current_period):
    u = _mk_candidate()
    client.force_login(u)
    resp = client.post(reverse("tuition"), {"status": "committed"})
    assert resp.status_code == 302
    enr = TuitionEnrollment.objects.get(user=u, tuition_period=current_period)
    assert enr.status == TuitionEnrollment.Status.COMMITTED


@pytest.mark.django_db
def test_post_updates_existing_enrollment(client, current_period):
    u = _mk_candidate()
    TuitionEnrollment.objects.create(
        user=u, tuition_period=current_period,
        status=TuitionEnrollment.Status.SKIPPING,
    )
    client.force_login(u)
    client.post(reverse("tuition"), {"status": "payment_plan"})
    enr = TuitionEnrollment.objects.get(user=u, tuition_period=current_period)
    assert enr.status == TuitionEnrollment.Status.PAYMENT_PLAN
    # Only one row — wasn't duplicated.
    assert TuitionEnrollment.objects.filter(
        user=u, tuition_period=current_period,
    ).count() == 1


@pytest.mark.django_db
def test_form_rejects_staff_only_statuses(client, current_period):
    """PAID_IN_FULL isn't student-selectable; it's reached via actual payment."""
    u = _mk_candidate()
    client.force_login(u)
    resp = client.post(reverse("tuition"), {"status": "paid_in_full"})
    assert resp.status_code == 200  # form re-renders with errors


# --- Backfill migration -------------------------------------------------


@pytest.mark.django_db
def test_seed_migration_created_a_period():
    """The data migration should have left at least one period in place."""
    assert TuitionPeriod.objects.exists()


# --- Reminder cron -------------------------------------------------------


@pytest.mark.django_db
def test_send_tuition_reminders_dry_run(current_period, mailoutbox):
    """Dry-run reports intended sends without dispatching email."""
    from io import StringIO

    from django.core.management import call_command

    _mk_candidate("a@x.test")
    _mk_candidate("b@x.test")
    # Push decision_due into the past so the gate opens.
    current_period.decision_due_date = current_period.start_date
    current_period.save()

    out = StringIO()
    call_command("send_tuition_reminders", "--dry-run", stdout=out)
    assert "would send" in out.getvalue().lower()
    assert len(mailoutbox) == 0  # dry-run does not actually send


@pytest.mark.django_db
def test_send_tuition_reminders_sends_to_undecided(current_period, mailoutbox):
    from io import StringIO

    from django.core.management import call_command

    from payments.models import TuitionReminder

    u = _mk_candidate("c@x.test")
    current_period.decision_due_date = current_period.start_date
    current_period.save()

    call_command("send_tuition_reminders", stdout=StringIO())
    assert len(mailoutbox) >= 1
    assert any(u.email in m.to for m in mailoutbox)
    assert TuitionReminder.objects.filter(user=u).exists()


@pytest.mark.django_db
def test_send_tuition_reminders_skips_skipping_status(current_period, mailoutbox):
    """A student who recorded SKIPPING shouldn't be pestered."""
    from io import StringIO

    from django.core.management import call_command

    u = _mk_candidate("d@x.test")
    TuitionEnrollment.objects.create(
        user=u, tuition_period=current_period,
        status=TuitionEnrollment.Status.SKIPPING,
    )
    current_period.decision_due_date = current_period.start_date
    current_period.save()

    call_command("send_tuition_reminders", stdout=StringIO())
    assert not any(u.email in m.to for m in mailoutbox)


@pytest.mark.django_db
def test_send_tuition_reminders_throttles_to_weekly(current_period, mailoutbox):
    """A user already reminded within the last week is skipped."""
    from io import StringIO

    from django.core.management import call_command

    from payments.models import TuitionReminder

    u = _mk_candidate("e@x.test")
    TuitionReminder.objects.create(user=u, tuition_period=current_period)
    current_period.decision_due_date = current_period.start_date
    current_period.save()

    call_command("send_tuition_reminders", stdout=StringIO())
    assert not any(u.email in m.to for m in mailoutbox)


@pytest.mark.django_db
def test_send_tuition_reminders_holds_before_decision_due(current_period, mailoutbox):
    """Pre-decision-due-date, the cron is a no-op."""
    from io import StringIO

    from django.core.management import call_command

    _mk_candidate("f@x.test")
    # Force decision_due_date into the future.
    current_period.decision_due_date = current_period.end_date
    current_period.save()

    call_command("send_tuition_reminders", stdout=StringIO())
    assert len(mailoutbox) == 0


# --- Treasurer dashboard tuition section --------------------------------


@pytest.fixture
def staff_user(db):
    u = User.objects.create_user(email="staff@x.test", password="x")
    u.is_staff = True
    u.save()
    return u


@pytest.mark.django_db
def test_treasurer_dashboard_shows_tuition_section(client, staff_user, current_period):
    _mk_candidate("c1@x.test")  # undecided
    u_committed = _mk_candidate("c2@x.test")
    TuitionEnrollment.objects.create(
        user=u_committed, tuition_period=current_period,
        status=TuitionEnrollment.Status.COMMITTED,
    )
    u_paid = _mk_candidate("c3@x.test")
    TuitionEnrollment.objects.create(
        user=u_paid, tuition_period=current_period,
        status=TuitionEnrollment.Status.PAID_IN_FULL,
    )

    client.force_login(staff_user)
    resp = client.get(reverse("treasurer_tuition"))
    assert resp.status_code == 200
    body = resp.content
    assert b"Tuition" in body
    assert current_period.name.encode() in body
    # Counts: 1 paid, 1 committed, 1 undecided.
    assert b"Reconciliation queue" in body
    assert b"c1@x.test" in body  # undecided
    assert b"c2@x.test" in body  # committed
    # PAID c3 should NOT appear in the tuition reconciliation queue.
    assert b"c3@x.test" not in body


@pytest.mark.django_db
def test_treasurer_dashboard_tuition_counts_collected(
    client, staff_user, current_period,
):
    """The Collected card sums successful TUITION payments linked through
    installments to the current period."""
    from decimal import Decimal as D

    from payments.models import (
        Payment,
        TuitionInstallment,
    )

    u = _mk_candidate("c4@x.test")
    enr = TuitionEnrollment.objects.create(
        user=u, tuition_period=current_period,
        status=TuitionEnrollment.Status.PAYMENT_PLAN,
    )
    inst = TuitionInstallment.objects.create(
        enrollment=enr, sequence=1,
        due_date=current_period.start_date, amount=D("400.00"),
    )
    Payment.objects.create(
        payment_type=Payment.Type.TUITION,
        user=u, amount=D("400.00"),
        status=Payment.Status.SUCCEEDED,
        tuition_installment=inst,
    )
    # An unrelated PENDING tuition payment shouldn't count.
    Payment.objects.create(
        payment_type=Payment.Type.TUITION,
        user=u, amount=D("400.00"),
        status=Payment.Status.PENDING,
        tuition_installment=inst,
    )

    client.force_login(staff_user)
    resp = client.get("/treasurer/")
    assert resp.status_code == 200
    assert b"$400.00" in resp.content


@pytest.mark.django_db
def test_treasurer_dashboard_handles_no_period(client, staff_user):
    """Renders politely when no TuitionPeriod is configured."""
    from payments.models import TuitionPeriod
    TuitionPeriod.objects.all().delete()
    client.force_login(staff_user)
    resp = client.get("/treasurer/")
    assert resp.status_code == 200
    assert b"No current academic year configured" in resp.content


@pytest.mark.django_db
def test_treasurer_dashboard_requires_staff(client, current_period):
    """Non-staff users can't see the dashboard."""
    u = _mk_candidate("nope@x.test")
    client.force_login(u)
    resp = client.get("/treasurer/")
    # treasurer_dashboard uses user_passes_test which redirects to login.
    assert resp.status_code == 302


# --- Treasurer admin tabs -----------------------------------------------


@pytest.mark.django_db
def test_treasurer_overview_shows_both_dues_and_tuition_cards(
    client, staff_user, current_period,
):
    client.force_login(staff_user)
    resp = client.get(reverse("treasurer"))
    assert resp.status_code == 200
    body = resp.content
    assert b"Dues" in body
    assert b"Tuition" in body
    # Tab nav should include all four tabs.
    for label in (b"Overview", b"Tuition", b"Dues", b"Settings"):
        assert label in body


@pytest.mark.django_db
def test_treasurer_tabs_all_require_staff(client, current_period):
    """All four tabs are gated by the staff check."""
    u = _mk_candidate("not-staff@x.test")
    client.force_login(u)
    for name in ("treasurer", "treasurer_tuition", "treasurer_dues", "treasurer_settings"):
        assert client.get(reverse(name)).status_code == 302


def _settings_post_data(
    dues_periods, tuition_periods,
    *, dues_overrides=None, tuition_overrides=None,
):
    """Build a flat POST dict for the treasurer-settings formsets.

    `dues_overrides` / `tuition_overrides` are dicts keyed by period.id
    that override the default per-row values.
    """
    dues_overrides = dues_overrides or {}
    tuition_overrides = tuition_overrides or {}
    data = {
        "dues-TOTAL_FORMS":      str(len(dues_periods)),
        "dues-INITIAL_FORMS":    str(len(dues_periods)),
        "dues-MIN_NUM_FORMS":    "0",
        "dues-MAX_NUM_FORMS":    "1000",
        "tuition-TOTAL_FORMS":   str(len(tuition_periods)),
        "tuition-INITIAL_FORMS": str(len(tuition_periods)),
        "tuition-MIN_NUM_FORMS": "0",
        "tuition-MAX_NUM_FORMS": "1000",
    }
    for i, p in enumerate(dues_periods):
        row = {
            "dues_amount_pre_candidate": str(p.dues_amount_pre_candidate),
            "dues_amount_candidate":     str(p.dues_amount_candidate),
            "dues_amount_analyst":       str(p.dues_amount_analyst),
            "reminder_interval_days":    str(p.reminder_interval_days),
        }
        row.update(dues_overrides.get(p.id, {}))
        for k, v in row.items():
            data[f"dues-{i}-{k}"] = v
        data[f"dues-{i}-id"] = str(p.id)
    for i, p in enumerate(tuition_periods):
        row = {
            "tuition_amount":         str(p.tuition_amount),
            "reminder_interval_days": str(p.reminder_interval_days),
        }
        row.update(tuition_overrides.get(p.id, {}))
        for k, v in row.items():
            data[f"tuition-{i}-{k}"] = v
        data[f"tuition-{i}-id"] = str(p.id)
    return data


@pytest.mark.django_db
def test_treasurer_settings_renders_with_form(
    client, staff_user, current_period,
):
    client.force_login(staff_user)
    resp = client.get(reverse("treasurer_settings"))
    assert resp.status_code == 200
    body = resp.content
    assert b"Dues" in body
    assert b"Tuition" in body
    # Form fields by formset-prefixed name.
    for field in (b"dues-0-dues_amount_pre_candidate", b"dues-0-dues_amount_candidate",
                  b"dues-0-dues_amount_analyst", b"tuition-0-tuition_amount"):
        assert field in body


@pytest.mark.django_db
def test_treasurer_settings_post_updates_both_periods(
    client, staff_user, current_period,
):
    from payments.models import DuesPeriod
    dues_period = DuesPeriod.current()
    assert dues_period is not None
    client.force_login(staff_user)
    dues_periods    = list(DuesPeriod.objects.order_by("-start_date"))
    tuition_periods = list(TuitionPeriod.objects.order_by("-start_date"))
    data = _settings_post_data(
        dues_periods, tuition_periods,
        dues_overrides={dues_period.id: {
            "dues_amount_pre_candidate": "60",
            "dues_amount_candidate":     "120",
            "dues_amount_analyst":       "180",
        }},
        tuition_overrides={current_period.id: {"tuition_amount": "850"}},
    )
    resp = client.post(reverse("treasurer_settings"), data)
    assert resp.status_code == 302
    assert "saved=1" in resp.url
    dues_period.refresh_from_db()
    current_period.refresh_from_db()
    assert dues_period.dues_amount_pre_candidate == Decimal("60.00")
    assert dues_period.dues_amount_candidate     == Decimal("120.00")
    assert dues_period.dues_amount_analyst       == Decimal("180.00")
    assert current_period.tuition_amount         == Decimal("850.00")


@pytest.mark.django_db
def test_treasurer_settings_rejects_negative_amounts(
    client, staff_user, current_period,
):
    from payments.models import DuesPeriod
    dues_period = DuesPeriod.current()
    client.force_login(staff_user)
    dues_periods    = list(DuesPeriod.objects.order_by("-start_date"))
    tuition_periods = list(TuitionPeriod.objects.order_by("-start_date"))
    data = _settings_post_data(
        dues_periods, tuition_periods,
        dues_overrides={dues_period.id: {"dues_amount_pre_candidate": "-1"}},
    )
    resp = client.post(reverse("treasurer_settings"), data)
    assert resp.status_code == 200  # form re-renders with errors


@pytest.mark.django_db
def test_treasurer_settings_saves_reminder_cadence(
    client, staff_user, current_period,
):
    """Cadence inputs round-trip to both DuesPeriod and TuitionPeriod."""
    from payments.models import DuesPeriod
    dues_period = DuesPeriod.current()
    client.force_login(staff_user)
    dues_periods    = list(DuesPeriod.objects.order_by("-start_date"))
    tuition_periods = list(TuitionPeriod.objects.order_by("-start_date"))
    data = _settings_post_data(
        dues_periods, tuition_periods,
        dues_overrides={dues_period.id: {"reminder_interval_days": "14"}},
        tuition_overrides={current_period.id: {"reminder_interval_days": "10"}},
    )
    resp = client.post(reverse("treasurer_settings"), data)
    assert resp.status_code == 302
    dues_period.refresh_from_db()
    current_period.refresh_from_db()
    assert dues_period.reminder_interval_days == 14
    assert current_period.reminder_interval_days == 10


@pytest.mark.django_db
def test_send_tuition_reminders_respects_period_cadence(
    current_period, mailoutbox,
):
    """A 14-day cadence skips users reminded within the past 14 days."""
    from datetime import timedelta
    from io import StringIO

    from django.core.management import call_command
    from django.utils import timezone

    from payments.models import TuitionReminder

    current_period.decision_due_date = current_period.start_date
    current_period.reminder_interval_days = 14
    current_period.save()

    u = _mk_candidate("cad@x.test")
    # Reminded 10 days ago — under the 14-day cadence, should NOT send again.
    TuitionReminder.objects.create(user=u, tuition_period=current_period)
    TuitionReminder.objects.filter(user=u).update(
        sent_at=timezone.now() - timedelta(days=10)
    )
    call_command("send_tuition_reminders", stdout=StringIO())
    assert not any(u.email in m.to for m in mailoutbox)


@pytest.mark.django_db
def test_treasurer_tuition_set_status_records_skipping(
    client, staff_user, current_period,
):
    """Inline 'Skipping' button creates the enrollment with that status."""
    u = _mk_candidate("set-skip@x.test")
    client.force_login(staff_user)
    resp = client.post(
        reverse("treasurer_tuition_set_status", args=[u.id]),
        {"status": "skipping"},
    )
    assert resp.status_code == 302
    enr = TuitionEnrollment.objects.get(user=u, tuition_period=current_period)
    assert enr.status == TuitionEnrollment.Status.SKIPPING
    # Audit trail recorded in notes.
    assert "set status to Skipping" in enr.notes
    assert staff_user.email in enr.notes


@pytest.mark.django_db
def test_treasurer_tuition_set_status_overrides_existing(
    client, staff_user, current_period,
):
    """An existing enrollment is updated, not duplicated."""
    u = _mk_candidate("set-override@x.test")
    TuitionEnrollment.objects.create(
        user=u, tuition_period=current_period,
        status=TuitionEnrollment.Status.COMMITTED,
    )
    client.force_login(staff_user)
    client.post(
        reverse("treasurer_tuition_set_status", args=[u.id]),
        {"status": "skipping"},
    )
    enrollments = TuitionEnrollment.objects.filter(user=u, tuition_period=current_period)
    assert enrollments.count() == 1
    assert enrollments.first().status == TuitionEnrollment.Status.SKIPPING


@pytest.mark.django_db
def test_treasurer_tuition_set_status_rejects_invalid_status(
    client, staff_user, current_period,
):
    """Status values not in the inline whitelist (e.g. 'paid_in_full') are
    silently no-op'd — those paths must go through proper payment recording."""
    u = _mk_candidate("set-invalid@x.test")
    client.force_login(staff_user)
    client.post(
        reverse("treasurer_tuition_set_status", args=[u.id]),
        {"status": "paid_in_full"},
    )
    assert not TuitionEnrollment.objects.filter(
        user=u, tuition_period=current_period,
    ).exists()


@pytest.mark.django_db
def test_treasurer_tuition_record_offline_payment_flips_to_paid_in_full(
    client, staff_user, current_period,
):
    """Record-offline creates installment + payment, runs complete_payment,
    enrollment lands on PAID_IN_FULL."""
    from payments.models import Payment, TuitionInstallment

    u = _mk_candidate("offline-pay@x.test")
    client.force_login(staff_user)
    resp = client.post(
        reverse("treasurer_tuition_record_offline_payment", args=[u.id])
    )
    assert resp.status_code == 302
    enr = TuitionEnrollment.objects.get(user=u, tuition_period=current_period)
    assert enr.status == TuitionEnrollment.Status.PAID_IN_FULL
    inst = TuitionInstallment.objects.get(enrollment=enr)
    assert inst.paid is True
    payment = Payment.objects.get(user=u, payment_type=Payment.Type.TUITION)
    assert payment.method == Payment.Method.OFFLINE
    assert payment.status == Payment.Status.SUCCEEDED
    assert staff_user.email in payment.notes


@pytest.mark.django_db
def test_treasurer_tuition_actions_require_staff(client, current_period):
    """Non-staff can't trigger the resolution actions."""
    u = _mk_candidate("anyone@x.test")
    client.force_login(u)
    for name in ("treasurer_tuition_set_status",
                 "treasurer_tuition_record_offline_payment"):
        resp = client.post(reverse(name, args=[u.id]), {"status": "skipping"})
        assert resp.status_code == 302
        assert "/accounts/login/" in resp.url


# --- Treasurer offline dues payment recording ---------------------------


@pytest.mark.django_db
def test_treasurer_dues_record_offline_payment_creates_succeeded_payment(
    client, staff_user,
):
    """Records a SUCCEEDED Payment for the user's role-tier amount."""
    from payments.models import DuesPeriod, Payment

    u = _mk_candidate("dues-off@x.test")
    period = DuesPeriod.current()
    assert period is not None
    expected_amount = period.amount_for_role(u.profile.role)
    client.force_login(staff_user)
    resp = client.post(
        reverse("treasurer_dues_record_offline_payment", args=[u.id])
    )
    assert resp.status_code == 302
    payment = Payment.objects.get(user=u, payment_type=Payment.Type.DUES)
    assert payment.status == Payment.Status.SUCCEEDED
    assert payment.method == Payment.Method.OFFLINE
    assert payment.amount == expected_amount
    assert payment.dues_period == period
    assert staff_user.email in payment.notes


@pytest.mark.django_db
def test_treasurer_dues_record_offline_payment_skips_non_obligated(
    client, staff_user,
):
    """Roles outside the tier table (e.g. external) → no Payment created."""
    from payments.models import Payment

    u = User.objects.create_user(email="ext@x.test", password="x")
    u.profile.role = Profile.Role.EXTERNAL
    u.profile.save()
    client.force_login(staff_user)
    resp = client.post(
        reverse("treasurer_dues_record_offline_payment", args=[u.id])
    )
    assert resp.status_code == 302
    assert not Payment.objects.filter(user=u).exists()


@pytest.mark.django_db
def test_treasurer_dues_record_offline_payment_requires_staff(client):
    from payments.models import Payment

    u = User.objects.create_user(email="not-staff@x.test", password="x")
    u.profile.role = Profile.Role.CANDIDATE
    u.profile.save()
    client.force_login(u)
    resp = client.post(
        reverse("treasurer_dues_record_offline_payment", args=[u.id])
    )
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.url
    assert not Payment.objects.filter(user=u).exists()


# --- Treasurer Exports + Payments tabs ----------------------------------


@pytest.mark.django_db
def test_treasurer_exports_tab_renders(client, staff_user):
    client.force_login(staff_user)
    resp = client.get(reverse("treasurer_exports"))
    assert resp.status_code == 200
    body = resp.content
    assert b"All transactions" in body
    assert b"Download CSV" in body


@pytest.mark.django_db
def test_treasurer_payments_tab_lists_payments(
    client, staff_user, current_period,
):
    from payments.models import DuesPeriod, Payment
    period = DuesPeriod.current()
    u = _mk_candidate("pay-list@x.test")
    Payment.objects.create(
        payment_type=Payment.Type.DUES,
        user=u, amount=period.amount_for_role("candidate"),
        status=Payment.Status.SUCCEEDED,
        dues_period=period,
        method=Payment.Method.OFFLINE,
    )
    client.force_login(staff_user)
    resp = client.get(reverse("treasurer_payments"))
    assert resp.status_code == 200
    body = resp.content
    assert b"pay-list@x.test" in body
    assert b"Dues" in body


@pytest.mark.django_db
def test_treasurer_payments_tab_filters_by_type(
    client, staff_user, current_period,
):
    from payments.models import DuesPeriod, Payment
    period = DuesPeriod.current()
    u_dues = _mk_candidate("dues-only@x.test")
    u_don = _mk_candidate("don-only@x.test")
    Payment.objects.create(
        payment_type=Payment.Type.DUES, user=u_dues, amount=Decimal("100"),
        status=Payment.Status.SUCCEEDED, dues_period=period,
    )
    Payment.objects.create(
        payment_type=Payment.Type.DONATION, user=u_don, amount=Decimal("50"),
        status=Payment.Status.SUCCEEDED,
    )
    client.force_login(staff_user)
    resp = client.get(reverse("treasurer_payments") + "?type=donation")
    body = resp.content
    assert b"don-only@x.test" in body
    assert b"dues-only@x.test" not in body


@pytest.mark.django_db
def test_treasurer_payment_apply_success_marks_paid(
    client, staff_user, current_period,
):
    """Mark paid button on a PENDING offline payment runs complete_payment."""
    from payments.models import DuesPeriod, Payment
    period = DuesPeriod.current()
    u = _mk_candidate("pending-pay@x.test")
    p = Payment.objects.create(
        payment_type=Payment.Type.DUES,
        user=u, amount=period.amount_for_role("candidate"),
        status=Payment.Status.PENDING,
        method=Payment.Method.OFFLINE,
        dues_period=period,
    )
    client.force_login(staff_user)
    resp = client.post(reverse("treasurer_payment_apply_success", args=[p.id]))
    assert resp.status_code == 302
    p.refresh_from_db()
    assert p.status == Payment.Status.SUCCEEDED


@pytest.mark.django_db
def test_treasurer_payment_refund_skips_non_stripe_payments(
    client, staff_user, current_period,
):
    """Offline payments don't have a Stripe charge — refund no-ops."""
    from payments.models import DuesPeriod, Payment
    period = DuesPeriod.current()
    u = _mk_candidate("offline-no-refund@x.test")
    p = Payment.objects.create(
        payment_type=Payment.Type.DUES,
        user=u, amount=period.amount_for_role("candidate"),
        status=Payment.Status.SUCCEEDED,
        method=Payment.Method.OFFLINE,
        dues_period=period,
    )
    client.force_login(staff_user)
    resp = client.post(reverse("treasurer_payment_refund", args=[p.id]))
    assert resp.status_code == 302
    p.refresh_from_db()
    # Status unchanged — offline payment wasn't Stripe-refunded.
    assert p.status == Payment.Status.SUCCEEDED


@pytest.mark.django_db
def test_create_dues_period_if_needed_keeps_two_years_ahead(db):
    """Rollover should always maintain current + next AY for dues."""
    from datetime import date
    from io import StringIO

    from django.core.management import call_command

    from payments.models import DuesPeriod

    DuesPeriod.objects.all().delete()
    call_command("create_dues_period_if_needed", stdout=StringIO())

    today = date.today()
    if today.month >= 9:
        current_start = today.year
    else:
        current_start = today.year - 1
    actual = set(DuesPeriod.objects.values_list("slug", flat=True))
    assert f"ay-{current_start}-{current_start + 1}" in actual
    assert f"ay-{current_start + 1}-{current_start + 2}" in actual


@pytest.mark.django_db
def test_create_tuition_period_if_needed_keeps_two_years_ahead(db):
    """Rollover should always maintain current + next AY for tuition."""
    from datetime import date
    from io import StringIO

    from django.core.management import call_command

    from payments.models import TuitionPeriod

    TuitionPeriod.objects.all().delete()
    call_command("create_tuition_period_if_needed", stdout=StringIO())

    today = date.today()
    if today.month >= 9:
        current_start = today.year
    else:
        current_start = today.year - 1
    actual = set(TuitionPeriod.objects.values_list("slug", flat=True))
    assert f"ay-{current_start}-{current_start + 1}-tuition" in actual
    assert f"ay-{current_start + 1}-{current_start + 2}-tuition" in actual


@pytest.mark.django_db
def test_treasurer_help_renders_markdown(client, staff_user):
    """Help tab renders the treasurer guide markdown doc with cross-link."""
    client.force_login(staff_user)
    resp = client.get(reverse("treasurer_help"))
    assert resp.status_code == 200
    body = resp.content
    assert b"<h1>Treasurer Admin Guide" in body
    # Cross-reference to the PC admin guide.
    assert b"/program-admin/help/" in body


@pytest.mark.django_db
def test_treasurer_new_tabs_require_staff(client, current_period):
    """Exports + Payments + Members tabs gated to staff."""
    u = _mk_candidate("not-staff-tab@x.test")
    client.force_login(u)
    for name in ("treasurer_exports", "treasurer_payments", "treasurer_members"):
        resp = client.get(reverse(name))
        assert resp.status_code == 302


# --- Members tab --------------------------------------------------------


@pytest.mark.django_db
def test_treasurer_members_search_finds_matching_users(client, staff_user):
    _mk_candidate("alice@x.test")
    _mk_candidate("bob@x.test")
    client.force_login(staff_user)
    resp = client.get(reverse("treasurer_members") + "?q=alice")
    body = resp.content
    assert b"alice@x.test" in body
    assert b"bob@x.test" not in body


@pytest.mark.django_db
def test_treasurer_members_empty_search_shows_form_only(client, staff_user):
    _mk_candidate("anyone@x.test")
    client.force_login(staff_user)
    resp = client.get(reverse("treasurer_members"))
    body = resp.content
    assert b"Search by name or email" in body
    assert b"anyone@x.test" not in body


@pytest.mark.django_db
def test_treasurer_member_detail_shows_payments_and_enrollments(
    client, staff_user, current_period,
):
    from payments.models import DuesPeriod, Payment
    u = _mk_candidate("histo@x.test")
    period = DuesPeriod.current()
    Payment.objects.create(
        payment_type=Payment.Type.DUES,
        user=u, amount=period.amount_for_role("candidate"),
        status=Payment.Status.SUCCEEDED,
        dues_period=period,
    )
    TuitionEnrollment.objects.create(
        user=u, tuition_period=current_period,
        status=TuitionEnrollment.Status.COMMITTED,
    )
    client.force_login(staff_user)
    resp = client.get(reverse("treasurer_member_detail", args=[u.id]))
    assert resp.status_code == 200
    body = resp.content
    assert b"histo@x.test" in body
    assert b"Tuition enrollments" in body
    assert b"Payments" in body
    assert b"Committed" in body
    assert b"$100" in body  # the dues amount


@pytest.mark.django_db
def test_treasurer_settings_handles_missing_periods(client, staff_user):
    """Settings page renders even when no periods are configured."""
    from payments.models import DuesPeriod, TuitionPeriod
    TuitionPeriod.objects.all().delete()
    DuesPeriod.objects.all().delete()
    client.force_login(staff_user)
    resp = client.get(reverse("treasurer_settings"))
    assert resp.status_code == 200
    body = resp.content
    assert b"No academic years configured for dues yet" in body
    assert b"No academic years configured for tuition yet" in body


# --- Auto-flip on tuition payment success -------------------------------


@pytest.mark.django_db
def test_paying_only_installment_flips_enrollment_to_paid_in_full(current_period):
    """Pay-in-full (single installment): payment success → enrollment becomes PAID_IN_FULL."""
    from decimal import Decimal as D

    from payments.models import Payment, TuitionInstallment
    from payments.operations import complete_payment

    u = _mk_candidate("pf@x.test")
    enr = TuitionEnrollment.objects.create(
        user=u, tuition_period=current_period,
        status=TuitionEnrollment.Status.COMMITTED,
    )
    inst = TuitionInstallment.objects.create(
        enrollment=enr, sequence=1,
        due_date=current_period.start_date, amount=D("800.00"),
    )
    payment = Payment.objects.create(
        payment_type=Payment.Type.TUITION,
        user=u, amount=D("800.00"),
        status=Payment.Status.PENDING,
        tuition_installment=inst,
    )

    complete_payment(payment)

    inst.refresh_from_db()
    enr.refresh_from_db()
    assert inst.paid is True
    assert enr.status == TuitionEnrollment.Status.PAID_IN_FULL


@pytest.mark.django_db
def test_paying_first_of_two_installments_keeps_payment_plan_status(current_period):
    """With multiple installments, paying one doesn't flip the enrollment yet."""
    from decimal import Decimal as D

    from payments.models import Payment, TuitionInstallment
    from payments.operations import complete_payment

    u = _mk_candidate("pp@x.test")
    enr = TuitionEnrollment.objects.create(
        user=u, tuition_period=current_period,
        status=TuitionEnrollment.Status.PAYMENT_PLAN,
    )
    inst1 = TuitionInstallment.objects.create(
        enrollment=enr, sequence=1,
        due_date=current_period.start_date, amount=D("400.00"),
    )
    TuitionInstallment.objects.create(
        enrollment=enr, sequence=2,
        due_date=current_period.start_date, amount=D("400.00"),
    )
    payment = Payment.objects.create(
        payment_type=Payment.Type.TUITION,
        user=u, amount=D("400.00"),
        status=Payment.Status.PENDING,
        tuition_installment=inst1,
    )

    complete_payment(payment)

    inst1.refresh_from_db()
    enr.refresh_from_db()
    assert inst1.paid is True
    # Still PAYMENT_PLAN because installment 2 is unpaid.
    assert enr.status == TuitionEnrollment.Status.PAYMENT_PLAN


@pytest.mark.django_db
def test_paying_last_installment_flips_enrollment_to_paid_in_full(current_period):
    """Paying the final unpaid installment flips PAYMENT_PLAN → PAID_IN_FULL."""
    from decimal import Decimal as D

    from payments.models import Payment, TuitionInstallment
    from payments.operations import complete_payment

    u = _mk_candidate("last@x.test")
    enr = TuitionEnrollment.objects.create(
        user=u, tuition_period=current_period,
        status=TuitionEnrollment.Status.PAYMENT_PLAN,
    )
    inst1 = TuitionInstallment.objects.create(
        enrollment=enr, sequence=1,
        due_date=current_period.start_date, amount=D("400.00"),
        paid=True,  # already paid (pre-existing)
    )
    inst2 = TuitionInstallment.objects.create(
        enrollment=enr, sequence=2,
        due_date=current_period.start_date, amount=D("400.00"),
    )
    payment = Payment.objects.create(
        payment_type=Payment.Type.TUITION,
        user=u, amount=D("400.00"),
        status=Payment.Status.PENDING,
        tuition_installment=inst2,
    )

    complete_payment(payment)

    inst1.refresh_from_db()
    inst2.refresh_from_db()
    enr.refresh_from_db()
    assert inst1.paid is True
    assert inst2.paid is True
    assert enr.status == TuitionEnrollment.Status.PAID_IN_FULL


# --- Stripe Checkout: pay in full, plan setup, pay installment -----------


@pytest.fixture
def stub_stripe(monkeypatch):
    """Replace create_tuition_session with a stub returning a fake URL."""
    from unittest.mock import MagicMock
    stub = MagicMock(return_value=MagicMock(url="https://stripe.test/sess/abc"))
    monkeypatch.setattr("payments.views.create_tuition_session", stub)
    return stub


@pytest.mark.django_db
def test_pay_in_full_creates_installment_and_payment(
    client, current_period, stub_stripe,
):
    from payments.models import Payment

    u = _mk_candidate("pif@x.test")
    TuitionEnrollment.objects.create(
        user=u, tuition_period=current_period,
        status=TuitionEnrollment.Status.COMMITTED,
    )
    client.force_login(u)
    resp = client.post(reverse("tuition_pay_in_full"))
    assert resp.status_code == 302
    assert resp.url.startswith("https://stripe.test/")
    # Exactly one full-amount installment + one PENDING tuition payment.
    inst = TuitionInstallment.objects.get(enrollment__user=u)
    assert inst.amount == current_period.tuition_amount
    payment = Payment.objects.get(user=u, payment_type=Payment.Type.TUITION)
    assert payment.status == Payment.Status.PENDING
    assert payment.tuition_installment_id == inst.id


@pytest.mark.django_db
def test_pay_in_full_blocked_if_no_enrollment(client, current_period, stub_stripe):
    u = _mk_candidate("no-enr@x.test")
    client.force_login(u)
    resp = client.post(reverse("tuition_pay_in_full"))
    # No enrollment → redirected back, no Stripe session.
    assert resp.status_code == 302
    stub_stripe.assert_not_called()


@pytest.mark.django_db
def test_pay_in_full_redirects_if_installments_already_exist(
    client, current_period, stub_stripe,
):
    """Don't mint a parallel "full" installment if a plan is already set up."""
    u = _mk_candidate("dup@x.test")
    enr = TuitionEnrollment.objects.create(
        user=u, tuition_period=current_period,
        status=TuitionEnrollment.Status.PAYMENT_PLAN,
    )
    TuitionInstallment.objects.create(
        enrollment=enr, sequence=1,
        due_date=current_period.start_date, amount=Decimal("400.00"),
    )
    client.force_login(u)
    resp = client.post(reverse("tuition_pay_in_full"))
    assert resp.status_code == 302
    stub_stripe.assert_not_called()
    # No second installment created.
    assert enr.installments.count() == 1


@pytest.mark.django_db
def test_setup_plan_creates_two_installments(client, current_period):
    u = _mk_candidate("plan2@x.test")
    enr = TuitionEnrollment.objects.create(
        user=u, tuition_period=current_period,
        status=TuitionEnrollment.Status.PAYMENT_PLAN,
    )
    client.force_login(u)
    resp = client.post(reverse("tuition_setup_plan"), {"installment_count": "2"})
    assert resp.status_code == 302
    insts = list(enr.installments.order_by("sequence"))
    assert len(insts) == 2
    # Amounts sum to total.
    assert insts[0].amount + insts[1].amount == current_period.tuition_amount
    # Second installment due in Feb of the next calendar year.
    assert insts[1].due_date.month == 2


@pytest.mark.django_db
def test_setup_plan_creates_nine_installments(client, current_period):
    u = _mk_candidate("plan9@x.test")
    enr = TuitionEnrollment.objects.create(
        user=u, tuition_period=current_period,
        status=TuitionEnrollment.Status.PAYMENT_PLAN,
    )
    client.force_login(u)
    resp = client.post(reverse("tuition_setup_plan"), {"installment_count": "9"})
    assert resp.status_code == 302
    insts = list(enr.installments.order_by("sequence"))
    assert len(insts) == 9
    # Amounts sum exactly to the period total (rounding goes on installment 9).
    assert sum(i.amount for i in insts) == current_period.tuition_amount


@pytest.mark.django_db
def test_setup_plan_rejects_invalid_count(client, current_period):
    u = _mk_candidate("badcount@x.test")
    enr = TuitionEnrollment.objects.create(
        user=u, tuition_period=current_period,
        status=TuitionEnrollment.Status.PAYMENT_PLAN,
    )
    client.force_login(u)
    resp = client.post(reverse("tuition_setup_plan"), {"installment_count": "5"})
    assert resp.status_code == 302
    assert enr.installments.count() == 0


@pytest.mark.django_db
def test_setup_plan_idempotent_when_installments_exist(client, current_period):
    """A duplicate POST doesn't multiply installments."""
    u = _mk_candidate("idem-plan@x.test")
    enr = TuitionEnrollment.objects.create(
        user=u, tuition_period=current_period,
        status=TuitionEnrollment.Status.PAYMENT_PLAN,
    )
    TuitionInstallment.objects.create(
        enrollment=enr, sequence=1,
        due_date=current_period.start_date, amount=Decimal("400.00"),
    )
    client.force_login(u)
    resp = client.post(reverse("tuition_setup_plan"), {"installment_count": "2"})
    assert resp.status_code == 302
    assert enr.installments.count() == 1


@pytest.mark.django_db
def test_pay_installment_creates_payment_and_redirects_to_stripe(
    client, current_period, stub_stripe,
):
    from payments.models import Payment

    u = _mk_candidate("pi@x.test")
    enr = TuitionEnrollment.objects.create(
        user=u, tuition_period=current_period,
        status=TuitionEnrollment.Status.PAYMENT_PLAN,
    )
    inst = TuitionInstallment.objects.create(
        enrollment=enr, sequence=1,
        due_date=current_period.start_date, amount=Decimal("400.00"),
    )
    client.force_login(u)
    resp = client.post(reverse("tuition_pay_installment", args=[inst.id]))
    assert resp.status_code == 302
    assert resp.url.startswith("https://stripe.test/")
    payment = Payment.objects.get(tuition_installment=inst)
    assert payment.status == Payment.Status.PENDING


@pytest.mark.django_db
def test_pay_installment_404_for_other_users_installment(
    client, current_period, stub_stripe,
):
    """User A cannot pay user B's installment."""
    user_a = _mk_candidate("a@x.test")
    user_b = _mk_candidate("b@x.test")
    enr_b = TuitionEnrollment.objects.create(
        user=user_b, tuition_period=current_period,
        status=TuitionEnrollment.Status.PAYMENT_PLAN,
    )
    inst_b = TuitionInstallment.objects.create(
        enrollment=enr_b, sequence=1,
        due_date=current_period.start_date, amount=Decimal("400.00"),
    )
    client.force_login(user_a)
    resp = client.post(reverse("tuition_pay_installment", args=[inst_b.id]))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_pay_installment_no_op_if_already_paid(
    client, current_period, stub_stripe,
):
    u = _mk_candidate("paid@x.test")
    enr = TuitionEnrollment.objects.create(
        user=u, tuition_period=current_period,
        status=TuitionEnrollment.Status.PAYMENT_PLAN,
    )
    inst = TuitionInstallment.objects.create(
        enrollment=enr, sequence=1,
        due_date=current_period.start_date, amount=Decimal("400.00"),
        paid=True,
    )
    client.force_login(u)
    resp = client.post(reverse("tuition_pay_installment", args=[inst.id]))
    assert resp.status_code == 302
    stub_stripe.assert_not_called()


@pytest.mark.django_db
def test_complete_payment_is_idempotent_for_tuition(current_period):
    """Calling complete_payment twice is a no-op the second time."""
    from decimal import Decimal as D

    from payments.models import Payment, TuitionInstallment
    from payments.operations import complete_payment

    u = _mk_candidate("idem@x.test")
    enr = TuitionEnrollment.objects.create(
        user=u, tuition_period=current_period,
        status=TuitionEnrollment.Status.COMMITTED,
    )
    inst = TuitionInstallment.objects.create(
        enrollment=enr, sequence=1,
        due_date=current_period.start_date, amount=D("800.00"),
    )
    payment = Payment.objects.create(
        payment_type=Payment.Type.TUITION,
        user=u, amount=D("800.00"),
        status=Payment.Status.PENDING,
        tuition_installment=inst,
    )

    complete_payment(payment)
    payment.refresh_from_db()
    inst.refresh_from_db()
    first_paid_at = inst.paid_at

    # Re-call: should not change anything.
    complete_payment(payment)
    inst.refresh_from_db()
    enr.refresh_from_db()
    assert inst.paid_at == first_paid_at
    assert enr.status == TuitionEnrollment.Status.PAID_IN_FULL
