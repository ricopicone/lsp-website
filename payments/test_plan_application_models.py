"""Model-layer building blocks for Board tuition payment-plan applications
(task #450 phase B): TuitionEnrollment.Status.PLAN_REQUESTED,
TuitionPeriod.upcoming()/clean(), and TuitionPlanApplication itself.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from accounts.models import User
from payments.models import TuitionEnrollment, TuitionPeriod, TuitionPlanApplication

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_seeded_periods():
    # A seed migration pre-populates TuitionPeriod rows; these tests want a
    # clean slate so upcoming()/current() behavior is unambiguous.
    TuitionPeriod.objects.all().delete()


@pytest.fixture
def member():
    u = User.objects.create_user(email="planapp@x.test", password="x")
    u.profile.role = "candidate"
    u.profile.save()
    return u


@pytest.fixture
def staffer():
    return User.objects.create_user(email="treasurer@x.test", password="x")


def _period(name, slug, start, end, decision_due, amount="1000", payment_due=None):
    return TuitionPeriod.objects.create(
        name=name, slug=slug, start_date=start, end_date=end,
        decision_due_date=decision_due, payment_due_date=payment_due,
        tuition_amount=Decimal(amount),
    )


# ------------------------------------------------------ PLAN_REQUESTED ---

def test_plan_requested_status_exists():
    assert TuitionEnrollment.Status.PLAN_REQUESTED == "plan_requested"


def test_plan_requested_does_not_cover_seminars(member):
    period = _period(
        "AY 2026-2027", "ay-2026-2027",
        date(2026, 9, 1), date(2027, 6, 30), date(2026, 10, 1),
    )
    enrollment = TuitionEnrollment.objects.create(
        user=member, tuition_period=period,
        status=TuitionEnrollment.Status.PLAN_REQUESTED, source="staff",
    )
    assert enrollment.covers_seminars is False


# ----------------------------------------------------------- upcoming() ---

def test_upcoming_returns_earliest_future_period():
    today = timezone_today()
    far = _period(
        "AY 2028-2029", "ay-2028-2029",
        today + timedelta(days=400), today + timedelta(days=700),
        today + timedelta(days=420),
    )
    near = _period(
        "AY 2027-2028", "ay-2027-2028",
        today + timedelta(days=30), today + timedelta(days=300),
        today + timedelta(days=45),
    )
    # A period already underway (or past) should not be picked as "upcoming".
    _period(
        "AY 2026-2027", "ay-2026-2027",
        today - timedelta(days=30), today + timedelta(days=200),
        today + timedelta(days=10),
    )
    assert TuitionPeriod.upcoming() == near
    assert far != TuitionPeriod.upcoming()


def test_upcoming_returns_none_with_no_future_rows():
    today = timezone_today()
    _period(
        "AY 2025-2026", "ay-2025-2026",
        today - timedelta(days=400), today - timedelta(days=30),
        today - timedelta(days=380),
    )
    assert TuitionPeriod.upcoming() is None


def timezone_today() -> date:
    from django.utils import timezone
    return timezone.now().date()


# --------------------------------------------------------------- clean() ---

def test_clean_rejects_payment_due_before_decision_due():
    period = TuitionPeriod(
        name="AY 2026-2027", slug="ay-2026-2027",
        start_date=date(2026, 9, 1), end_date=date(2027, 6, 30),
        decision_due_date=date(2026, 10, 15),
        payment_due_date=date(2026, 10, 1),  # earlier than decision_due_date
        tuition_amount=Decimal("1000"),
    )
    with pytest.raises(ValidationError):
        period.clean()


def test_clean_allows_payment_due_on_or_after_decision_due():
    period = TuitionPeriod(
        name="AY 2026-2027", slug="ay-2026-2027",
        start_date=date(2026, 9, 1), end_date=date(2027, 6, 30),
        decision_due_date=date(2026, 10, 15),
        payment_due_date=date(2026, 11, 1),
        tuition_amount=Decimal("1000"),
    )
    period.clean()  # does not raise


def test_clean_allows_missing_payment_due_date():
    period = TuitionPeriod(
        name="AY 2026-2027", slug="ay-2026-2027",
        start_date=date(2026, 9, 1), end_date=date(2027, 6, 30),
        decision_due_date=date(2026, 10, 15),
        payment_due_date=None,
        tuition_amount=Decimal("1000"),
    )
    period.clean()  # does not raise — existing fixtures omit payment_due_date


# ----------------------------------------------------- TuitionPlanApplication

def test_create_plan_application(member):
    period = _period(
        "AY 2026-2027", "ay-2026-2027",
        date(2026, 9, 1), date(2027, 6, 30), date(2026, 10, 1),
    )
    app = TuitionPlanApplication.objects.create(
        user=member, tuition_period=period, reasons="Reduced income this year.",
    )
    assert app.status == TuitionPlanApplication.Status.PENDING
    assert app.created_at is not None
    assert app.decided_by is None
    assert app.decided_at is None
    assert app.note == ""


def test_second_pending_application_same_user_period_raises(member):
    period = _period(
        "AY 2026-2027", "ay-2026-2027",
        date(2026, 9, 1), date(2027, 6, 30), date(2026, 10, 1),
    )
    TuitionPlanApplication.objects.create(
        user=member, tuition_period=period, reasons="First reason.",
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        TuitionPlanApplication.objects.create(
            user=member, tuition_period=period, reasons="Second reason.",
        )


def test_declined_then_new_pending_is_allowed(member, staffer):
    period = _period(
        "AY 2026-2027", "ay-2026-2027",
        date(2026, 9, 1), date(2027, 6, 30), date(2026, 10, 1),
    )
    first = TuitionPlanApplication.objects.create(
        user=member, tuition_period=period, reasons="First reason.",
    )
    first.status = TuitionPlanApplication.Status.DECLINED
    first.decided_by = staffer
    first.note = "Not this year."
    first.save()

    second = TuitionPlanApplication.objects.create(
        user=member, tuition_period=period, reasons="Second reason, resubmitted.",
    )
    assert second.status == TuitionPlanApplication.Status.PENDING
    assert TuitionPlanApplication.objects.filter(user=member, tuition_period=period).count() == 2


# --------------------------------------------------------------- notify ---

def _board_member(email="board@x.test"):
    from datetime import date as _date

    from committees.models import Committee
    from workgroups.models import WorkgroupMembership

    u = User.objects.create_user(email=email, password="x")
    Committee.objects.get(slug="board").add_member(
        u, role=WorkgroupMembership.Role.MEMBER, start_date=_date(2026, 1, 1),
    )
    return u


def test_submitting_notifies_board_not_applicant(member):
    from notifications.categories import Category
    from notifications.models import Notification
    from payments.notifications import notify_plan_application_submitted

    board_member = _board_member()
    period = _period(
        "AY 2026-2027", "ay-2026-2027",
        date(2026, 9, 1), date(2027, 6, 30), date(2026, 10, 1),
    )
    app = TuitionPlanApplication.objects.create(
        user=member, tuition_period=period, reasons="Reduced income this year.",
    )

    notify_plan_application_submitted(app)

    note = Notification.objects.get(recipient=board_member)
    assert note.category == Category.TUITION_PLAN_REVIEW
    assert not Notification.objects.filter(recipient=member).exists()


def test_submitting_does_not_notify_applicant_even_if_on_board(member):
    """A Board member applying for their own plan shouldn't get a
    reviewer-facing bell row about their own submission."""
    from datetime import date as _date

    from committees.models import Committee
    from notifications.models import Notification
    from payments.notifications import notify_plan_application_submitted
    from workgroups.models import WorkgroupMembership

    Committee.objects.get(slug="board").add_member(
        member, role=WorkgroupMembership.Role.MEMBER, start_date=_date(2026, 1, 1),
    )
    period = _period(
        "AY 2026-2027", "ay-2026-2027",
        date(2026, 9, 1), date(2027, 6, 30), date(2026, 10, 1),
    )
    app = TuitionPlanApplication.objects.create(
        user=member, tuition_period=period, reasons="Reduced income this year.",
    )

    notify_plan_application_submitted(app)

    assert not Notification.objects.filter(recipient=member).exists()


def test_deciding_notifies_applicant_approved(member, staffer):
    from notifications.categories import Category
    from notifications.models import Notification
    from payments.notifications import notify_plan_application_decided

    period = _period(
        "AY 2026-2027", "ay-2026-2027",
        date(2026, 9, 1), date(2027, 6, 30), date(2026, 10, 1),
    )
    app = TuitionPlanApplication.objects.create(
        user=member, tuition_period=period, reasons="Reduced income this year.",
    )
    app.status = TuitionPlanApplication.Status.APPROVED
    app.decided_by = staffer
    app.save()

    notify_plan_application_decided(app)

    note = Notification.objects.get(recipient=member)
    assert note.category == Category.TUITION_PLAN_REVIEW
    assert "approved" in note.title
    assert period.name in note.title


def test_deciding_notifies_applicant_declined(member, staffer):
    from notifications.models import Notification
    from payments.notifications import notify_plan_application_decided

    period = _period(
        "AY 2026-2027", "ay-2026-2027",
        date(2026, 9, 1), date(2027, 6, 30), date(2026, 10, 1),
    )
    app = TuitionPlanApplication.objects.create(
        user=member, tuition_period=period, reasons="Reduced income this year.",
    )
    app.status = TuitionPlanApplication.Status.DECLINED
    app.decided_by = staffer
    app.save()

    notify_plan_application_decided(app)

    note = Notification.objects.get(recipient=member)
    assert "unable to approve" in note.title
    assert "Account tab" in note.title
