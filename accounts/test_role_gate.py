"""Tuition clearance gate at the record_membership_change chokepoint (task #439)."""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from accounts.membership import current_academic_year_start, record_membership_change
from accounts.models import Profile, User
from payments.models import DuesPeriod, TuitionEnrollment, TuitionPeriod

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_periods():
    TuitionPeriod.objects.all().delete()
    DuesPeriod.objects.all().delete()


def _candidate_owing(email):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = "candidate"
    u.profile.save()
    tp = TuitionPeriod.objects.create(
        name="AY 2025-2026", slug="t-2025", start_date=date(2025, 9, 1),
        end_date=date(2026, 8, 31), decision_due_date=date(2025, 8, 31),
        tuition_amount=Decimal("2000"))
    TuitionEnrollment.objects.create(
        user=u, tuition_period=tp, status=TuitionEnrollment.Status.COMMITTED,
        source="staff")
    return u


def _promote(u, role="analyst"):
    return record_membership_change(
        u, role=role, standing=Profile.Standing.ACTIVE,
        effective_ay=current_academic_year_start())


def test_owing_candidate_cannot_become_analyst():
    u = _candidate_owing("rg1@x.test")
    with pytest.raises(ValidationError) as exc:
        _promote(u)
    assert any("uncovered" in m for m in exc.value.messages)
    assert any("treasurer account page" in m for m in exc.value.messages)
    u.profile.refresh_from_db()
    assert u.profile.role == "candidate"          # nothing changed
    assert u.tenures.count() <= 1                 # no tenure written


def test_external_to_analyst_passes_freely():
    u = User.objects.create_user(email="rg2@x.test", password="x")  # external
    _promote(u)
    u.profile.refresh_from_db()
    assert u.profile.role == "analyst"


def test_non_analyst_targets_unaffected():
    u = _candidate_owing("rg3@x.test")
    _promote(u, role="candidate")                 # lateral: no gate
    u.profile.refresh_from_db()
    assert u.profile.role == "candidate"


def test_settled_candidate_promotes():
    u = _candidate_owing("rg4@x.test")
    from payments.models import Charge
    for c in Charge.objects.filter(user=u):       # treasurer voids the charge
        c.status = Charge.Status.VOID
        c.staff_adjusted = True
        c.save()
    # …but 0 of 4 years covered still blocks:
    with pytest.raises(ValidationError):
        _promote(u)
