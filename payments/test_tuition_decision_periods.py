from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from payments.models import TuitionEnrollment, TuitionPeriod, TuitionPlanApplication

User = get_user_model()


@pytest.mark.django_db
def test_member_can_record_upcoming_year_decision(client):
    # Periods: one containing today, one future.
    import datetime
    today = datetime.date.today()
    cur = TuitionPeriod.objects.create(
        name="Cur", slug="cur", start_date=today.replace(month=1, day=1),
        decision_due_date=today, end_date=today.replace(month=12, day=31),
        tuition_amount=Decimal("2500"),
    )
    nxt = TuitionPeriod.objects.create(
        name="Next", slug="next",
        start_date=today.replace(year=today.year + 1, month=1, day=1),
        decision_due_date=today.replace(year=today.year + 1),
        end_date=today.replace(year=today.year + 1, month=12, day=31),
        tuition_amount=Decimal("2500"),
    )
    u = User.objects.create_user(email="d@example.com", password="x")
    u.profile.role = "candidate"
    u.profile.save(update_fields=["role"])
    client.force_login(u)

    client.post(reverse("tuition"), {"status": "skipping", "period": "next"})
    assert TuitionEnrollment.objects.filter(user=u, tuition_period=nxt).exists()
    assert not TuitionEnrollment.objects.filter(user=u, tuition_period=cur).exists()


# ---- Board payment-plan application (task #450 phase B) --------------------

@pytest.fixture
def cur_period(db):
    import datetime
    today = datetime.date.today()
    return TuitionPeriod.objects.create(
        name="Cur", slug="cur-plan", start_date=today.replace(month=1, day=1),
        decision_due_date=today, end_date=today.replace(month=12, day=31),
        tuition_amount=Decimal("2500"),
    )


@pytest.fixture
def applicant(db):
    u = User.objects.create_user(email="planner@example.com", password="x")
    u.profile.role = "candidate"
    u.profile.save(update_fields=["role"])
    return u


@pytest.mark.django_db
def test_payment_plan_without_reasons_writes_nothing(client, cur_period, applicant):
    client.force_login(applicant)
    resp = client.post(reverse("tuition"), {"status": "payment_plan"})
    assert resp.status_code == 302
    assert not TuitionEnrollment.objects.filter(user=applicant).exists()
    assert not TuitionPlanApplication.objects.filter(user=applicant).exists()


@pytest.mark.django_db
def test_payment_plan_with_reasons_creates_plan_requested_and_application(
    client, cur_period, applicant,
):
    client.force_login(applicant)
    resp = client.post(reverse("tuition"), {
        "status": "payment_plan",
        "reasons": "I lost my job and need to spread payments out.",
    })
    assert resp.status_code == 302

    enrollment = TuitionEnrollment.objects.get(user=applicant, tuition_period=cur_period)
    assert enrollment.status == TuitionEnrollment.Status.PLAN_REQUESTED

    application = TuitionPlanApplication.objects.get(
        user=applicant, tuition_period=cur_period,
    )
    assert application.status == TuitionPlanApplication.Status.PENDING
    assert application.reasons == "I lost my job and need to spread payments out."


@pytest.mark.django_db
def test_payment_plan_resubmit_while_pending_updates_reasons_not_duplicates(
    client, cur_period, applicant,
):
    client.force_login(applicant)
    client.post(reverse("tuition"), {
        "status": "payment_plan", "reasons": "First reason.",
    })
    client.post(reverse("tuition"), {
        "status": "payment_plan", "reasons": "Updated reason.",
    })

    assert TuitionPlanApplication.objects.filter(user=applicant).count() == 1
    application = TuitionPlanApplication.objects.get(user=applicant)
    assert application.reasons == "Updated reason."
    assert application.status == TuitionPlanApplication.Status.PENDING


@pytest.mark.django_db
def test_invalid_period_slug_falls_back_to_current_period(client, cur_period, applicant):
    client.force_login(applicant)
    resp = client.post(reverse("tuition"), {
        "status": "committed", "period": "not-a-real-slug",
    })
    assert resp.status_code == 302
    assert TuitionEnrollment.objects.filter(
        user=applicant, tuition_period=cur_period,
        status=TuitionEnrollment.Status.COMMITTED,
    ).exists()
