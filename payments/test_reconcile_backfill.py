"""Tests for the provisional-payment reconciliation view + tuition backfill."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, Source, User
from payments.models import Payment, TuitionEnrollment, TuitionPeriod

pytestmark = pytest.mark.django_db


def _period():
    return TuitionPeriod.objects.create(
        name="AY 2022–2023", slug="ay-2022-2023",
        start_date=date(2022, 9, 1), decision_due_date=date(2022, 10, 1),
        end_date=date(2023, 8, 31), tuition_amount=Decimal("2000.00"),
    )


def _student(email="s@x.test"):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = Profile.Role.CANDIDATE
    u.profile.save()
    return u


def _tuition_payment(user, amount, when, *, source=Source.IMPORTED):
    return Payment.objects.create(
        payment_type=Payment.Type.TUITION, user=user, amount=Decimal(amount),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.STRIPE,
        source=source, paid_at=timezone.make_aware(when),
    )


# ---- backfill_tuition_status ----------------------------------------------

def test_backfill_marks_paid_in_full():
    p = _period()
    u = _student()
    _tuition_payment(u, "2000.00", datetime(2022, 10, 1, 12))
    call_command("backfill_tuition_status", "--commit")
    e = TuitionEnrollment.objects.get(user=u, tuition_period=p)
    assert e.status == TuitionEnrollment.Status.PAID_IN_FULL
    assert e.source == Source.IMPORTED


def test_backfill_partial_is_payment_plan():
    p = _period()
    u = _student()
    _tuition_payment(u, "500.00", datetime(2022, 10, 1, 12))
    _tuition_payment(u, "500.00", datetime(2023, 1, 1, 12))  # $1000 < $2000
    call_command("backfill_tuition_status", "--commit")
    e = TuitionEnrollment.objects.get(user=u, tuition_period=p)
    assert e.status == TuitionEnrollment.Status.PAYMENT_PLAN


def test_backfill_dry_run_writes_nothing():
    _period()
    u = _student()
    _tuition_payment(u, "2000.00", datetime(2022, 10, 1, 12))
    call_command("backfill_tuition_status")
    assert not TuitionEnrollment.objects.exists()


def test_backfill_excludes_assumed_by_default():
    _period()
    u = _student()
    _tuition_payment(u, "2000.00", datetime(2022, 10, 1, 12), source=Source.ASSUMED)
    call_command("backfill_tuition_status", "--commit")
    assert not TuitionEnrollment.objects.exists()
    call_command("backfill_tuition_status", "--commit", "--include-assumed")
    assert TuitionEnrollment.objects.filter(user=u).exists()


def test_backfill_upgrades_but_does_not_downgrade():
    p = _period()
    u = _student()
    TuitionEnrollment.objects.create(
        user=u, tuition_period=p, status=TuitionEnrollment.Status.SKIPPING,
    )
    _tuition_payment(u, "2000.00", datetime(2022, 10, 1, 12))
    call_command("backfill_tuition_status", "--commit")
    e = TuitionEnrollment.objects.get(user=u, tuition_period=p)
    assert e.status == TuitionEnrollment.Status.PAID_IN_FULL  # skipping → paid

    # A later partial payment must NOT downgrade an existing paid-in-full row.
    _tuition_payment(u, "10.00", datetime(2022, 11, 1, 12))
    call_command("backfill_tuition_status", "--commit")
    e.refresh_from_db()
    assert e.status == TuitionEnrollment.Status.PAID_IN_FULL


# ---- reconcile view -------------------------------------------------------

def _treasurer(client):
    u = User.objects.create_user(email="treas@x.test", password="x", is_staff=True)
    client.force_login(u)
    return u


def test_reconcile_gated(client):
    client.force_login(User.objects.create_user(email="plain@x.test", password="x"))
    # The treasurer area uses user_passes_test, which redirects rather than 403s.
    assert client.get(reverse("treasurer_reconcile")).status_code == 302


def test_reconcile_lists_assumed_grouped(client):
    _treasurer(client)
    u = _student("karen@x.test")
    _tuition_payment(u, "60.00", datetime(2025, 10, 1, 12), source=Source.ASSUMED)
    _tuition_payment(u, "60.00", datetime(2025, 11, 1, 12), source=Source.ASSUMED)
    resp = client.get(reverse("treasurer_reconcile"))
    assert resp.status_code == 200
    assert b"karen@x.test" in resp.content


def test_reconcile_retypes_selected_payments(client):
    _treasurer(client)
    u = _student("karen@x.test")
    p1 = _tuition_payment(u, "60.00", datetime(2025, 10, 1, 12), source=Source.ASSUMED)
    p2 = _tuition_payment(u, "60.00", datetime(2025, 11, 1, 12), source=Source.ASSUMED)
    resp = client.post(reverse("treasurer_reconcile"), {
        "payment_ids": [p1.pk, p2.pk], "payment_type": "registration",
    })
    assert resp.status_code == 302
    rows = Payment.objects.filter(user=u)
    assert all(p.payment_type == "registration" for p in rows)
    assert all(p.source == Source.STAFF for p in rows)  # now staff-confirmed


def test_reconcile_leaves_unselected_payments(client):
    _treasurer(client)
    u = _student("karen@x.test")
    keep = _tuition_payment(u, "60.00", datetime(2025, 10, 1, 12), source=Source.ASSUMED)
    fix = _tuition_payment(u, "500.00", datetime(2025, 11, 1, 12), source=Source.ASSUMED)
    client.post(reverse("treasurer_reconcile"), {
        "payment_ids": [fix.pk], "payment_type": "registration",
    })
    keep.refresh_from_db()
    fix.refresh_from_db()
    assert fix.payment_type == "registration" and fix.source == Source.STAFF
    # The unselected one is untouched — still assumed tuition for next time.
    assert keep.payment_type == "tuition" and keep.source == Source.ASSUMED


def test_reconcile_requires_a_selection(client):
    _treasurer(client)
    u = _student("karen@x.test")
    _tuition_payment(u, "60.00", datetime(2025, 10, 1, 12), source=Source.ASSUMED)
    resp = client.post(reverse("treasurer_reconcile"), {"payment_type": "registration"})
    assert resp.status_code == 302  # redirects with an error, nothing changed
    assert Payment.objects.filter(source=Source.ASSUMED).count() == 1


def test_reconcile_links_unmatched_payer(client):
    _treasurer(client)
    member = _student("realmember@x.test")
    p = Payment.objects.create(
        payment_type=Payment.Type.TUITION, amount=Decimal("60.00"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.STRIPE,
        source=Source.ASSUMED, email="karen@x.test",
        paid_at=timezone.make_aware(datetime(2025, 10, 1, 12)),
        notes="[stripe-import:ch_x] (unmatched payer: Karen Benezra)",
    )
    resp = client.post(reverse("treasurer_reconcile"), {
        "payment_ids": [p.pk], "payment_type": "registration",
        "assign_user": "realmember@x.test",
    })
    assert resp.status_code == 302
    p.refresh_from_db()
    assert p.user == member and p.payment_type == "registration"
