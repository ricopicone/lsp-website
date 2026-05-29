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
    """EXEMPT and PAID_IN_FULL aren't student-selectable; admin-only."""
    u = _mk_candidate()
    client.force_login(u)
    for forbidden in ("exempt", "paid_in_full"):
        resp = client.post(reverse("tuition"), {"status": forbidden})
        assert resp.status_code == 200  # form re-renders with errors


# --- Backfill migration -------------------------------------------------


@pytest.mark.django_db
def test_seed_migration_created_a_period():
    """The data migration should have left at least one period in place."""
    assert TuitionPeriod.objects.exists()
