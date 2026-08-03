"""The Accounts roster distinguishes a plan that's current from one that's late
(task #494).

A member on an approved payment plan carries the whole year as owed from the
day they commit — the ledger keeps one annual charge whatever the schedule —
so "Owing" alone can't tell the treasurer whether they're behind. The marker
can.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import User
from payments.models import (
    Charge,
    DuesPeriod,
    TuitionEnrollment,
    TuitionInstallment,
    TuitionPeriod,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def treasurer(client):
    u = User.objects.create_user(email="tr@x.test", password="x", is_staff=True)
    client.force_login(u)
    return u


@pytest.fixture
def tuition_period(db):
    TuitionPeriod.objects.all().delete()
    today = date.today()
    return TuitionPeriod.objects.create(
        name="Current AY", slug="current-ay-tuition",
        start_date=today.replace(month=1, day=1),
        decision_due_date=today.replace(month=1, day=31),
        end_date=today.replace(month=12, day=31),
        tuition_amount=Decimal("2700"),
    )


def _plan_member(email, tuition_period, *, installment_due=None, paid=False):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = "pre_candidate"
    u.profile.save()
    # The enrollment's own sync mints the year's single tuition charge — a DB
    # unique constraint on (user, tuition_period) enforces one per year.
    enrollment = TuitionEnrollment.objects.create(
        user=u, tuition_period=tuition_period,
        status=TuitionEnrollment.Status.PAYMENT_PLAN,
    )
    if installment_due is not None:
        TuitionInstallment.objects.create(
            enrollment=enrollment, sequence=1, due_date=installment_due,
            amount=Decimal("300"), paid=paid,
        )
    return u


@pytest.fixture
def dues_period(db):
    DuesPeriod.objects.all().delete()
    return DuesPeriod.objects.create(
        name="AY 2026-2027", slug="ay-2026-2027",
        start_date=date(2026, 9, 1), due_date=date(2026, 9, 30),
        end_date=date(2027, 8, 31),
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"),
        dues_amount_analyst=Decimal("150"),
    )


def _row_for(resp, user):
    return next(r for r in resp.context["rows"] if r["user"].id == user.id)


def test_a_plan_that_is_paid_up_reads_as_current(
    client, treasurer, tuition_period, dues_period,
):
    member = _plan_member(
        "current@x.test", tuition_period,
        installment_due=date.today().replace(month=1, day=15), paid=True,
    )

    resp = client.get(reverse("treasurer_accounts"))

    assert _row_for(resp, member)["plan_state"] == "current"


def test_a_plan_with_an_overdue_installment_reads_as_overdue(
    client, treasurer, tuition_period, dues_period,
):
    member = _plan_member(
        "late@x.test", tuition_period,
        installment_due=date.today().replace(month=1, day=15),
    )

    resp = client.get(reverse("treasurer_accounts"))

    assert _row_for(resp, member)["plan_state"] == "overdue"


def test_a_member_not_on_a_plan_carries_no_marker(
    client, treasurer, tuition_period, dues_period,
):
    member = User.objects.create_user(email="plain@x.test", password="x")
    member.profile.role = "candidate"
    member.profile.save()
    Charge.objects.create(
        user=member, category=Charge.Category.DUES, amount=Decimal("100"),
        effective_date=dues_period.start_date, dues_period=dues_period,
    )

    resp = client.get(reverse("treasurer_accounts"))

    assert _row_for(resp, member)["plan_state"] is None


def test_the_overdue_marker_is_rendered(
    client, treasurer, tuition_period, dues_period,
):
    _plan_member(
        "late@x.test", tuition_period,
        installment_due=date.today().replace(month=1, day=15),
    )

    resp = client.get(reverse("treasurer_accounts"))

    assert b"plan overdue" in resp.content
