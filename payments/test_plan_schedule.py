"""The payment-plan schedule helpers (task #494).

``payments.plans`` is the one place that answers "what does this plan owe
right now?" — shared by the tuition reminder (which nudges on it), the
balance reminder (which spares members who are current on it), and the
treasurer's Accounts marker (which labels it).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from payments import plans
from payments.models import TuitionEnrollment, TuitionInstallment, TuitionPeriod
from payments.testing import make_period

User = get_user_model()

TODAY = date(2026, 11, 15)


@pytest.fixture
def period(db):
    return make_period(TuitionPeriod, 
        name="AY 2026–2027", slug="ay-2026-2027-tuition",
        start_date=date(2026, 9, 1), decision_due_date=date(2026, 10, 31),
        payment_due_date=date(2026, 11, 30), end_date=date(2027, 8, 31),
        tuition_amount=Decimal("2700"),
    )


@pytest.fixture
def student(db):
    u = User.objects.create_user(email="plan@example.com", password="x")
    u.profile.role = "pre_candidate"
    u.profile.save(update_fields=["role"])
    return u


@pytest.fixture
def enrollment(period, student):
    return TuitionEnrollment.objects.create(
        user=student, tuition_period=period,
        status=TuitionEnrollment.Status.PAYMENT_PLAN,
    )


def _installment(enrollment, sequence, due_date, *, paid=False):
    return TuitionInstallment.objects.create(
        enrollment=enrollment, sequence=sequence, due_date=due_date,
        amount=Decimal("300"), paid=paid,
    )


@pytest.mark.django_db
def test_no_installment_due_when_the_next_one_is_beyond_the_lead_window(enrollment):
    _installment(enrollment, 1, date(2026, 12, 1))  # 16 days out

    assert plans.due_installment(enrollment, TODAY) is None


@pytest.mark.django_db
def test_an_installment_inside_the_lead_window_comes_due(enrollment):
    upcoming = _installment(enrollment, 1, date(2026, 11, 20))  # 5 days out

    assert plans.due_installment(enrollment, TODAY) == upcoming


@pytest.mark.django_db
def test_the_oldest_overdue_installment_wins_over_an_upcoming_one(enrollment):
    overdue = _installment(enrollment, 1, date(2026, 10, 1))
    _installment(enrollment, 2, date(2026, 11, 1))
    _installment(enrollment, 3, date(2026, 11, 20))

    assert plans.due_installment(enrollment, TODAY) == overdue


@pytest.mark.django_db
def test_paid_installments_are_never_due(enrollment):
    _installment(enrollment, 1, date(2026, 10, 1), paid=True)
    _installment(enrollment, 2, date(2026, 12, 1))

    assert plans.due_installment(enrollment, TODAY) is None


@pytest.mark.django_db
def test_plan_states_marks_an_overdue_plan_overdue(enrollment, student):
    _installment(enrollment, 1, date(2026, 10, 1))

    assert plans.plan_states(TODAY)[student.id] == plans.State.OVERDUE


@pytest.mark.django_db
def test_plan_states_marks_a_plan_paid_up_to_date_current(enrollment, student):
    _installment(enrollment, 1, date(2026, 10, 1), paid=True)
    _installment(enrollment, 2, date(2026, 12, 1))

    assert plans.plan_states(TODAY)[student.id] == plans.State.CURRENT


@pytest.mark.django_db
def test_plan_states_marks_an_approved_plan_with_no_schedule_current(
    enrollment, student,
):
    """Approval alone creates no installments — nothing is late yet."""
    assert plans.plan_states(TODAY)[student.id] == plans.State.CURRENT


@pytest.mark.django_db
def test_plan_states_marks_a_pending_application_requested(enrollment, student):
    enrollment.status = TuitionEnrollment.Status.PLAN_REQUESTED
    enrollment.save(update_fields=["status"])

    assert plans.plan_states(TODAY)[student.id] == plans.State.REQUESTED


@pytest.mark.django_db
def test_plan_states_ignores_members_who_are_not_on_a_plan(enrollment, student):
    enrollment.status = TuitionEnrollment.Status.COMMITTED
    enrollment.save(update_fields=["status"])

    assert student.id not in plans.plan_states(TODAY)
