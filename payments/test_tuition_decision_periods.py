from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from payments.models import (
    TuitionEnrollment,
    TuitionInstallment,
    TuitionPeriod,
    TuitionPlanApplication,
)
from payments.testing import make_period

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
    # The view falls back to TuitionPeriod.current(), which is .first() by pk:
    # the clock-seeded period (payments/0006) covers today from Sept 1 and
    # would win over this one, so make this the only current period.
    TuitionPeriod.objects.filter(start_date__lte=today, end_date__gte=today).delete()
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


# ---- Pay-in-full and plan setup honor the upcoming period (task #450 #5) ---

@pytest.fixture
def stub_stripe(monkeypatch):
    """Replace create_tuition_session with a stub returning a fake URL."""
    from unittest.mock import MagicMock
    stub = MagicMock(return_value=MagicMock(url="https://stripe.test/sess/abc"))
    monkeypatch.setattr("payments.views.create_tuition_session", stub)
    return stub


@pytest.fixture
def two_periods(db):
    import datetime
    today = datetime.date.today()
    cur = TuitionPeriod.objects.create(
        name="Cur", slug="pif-cur", start_date=today.replace(month=1, day=1),
        decision_due_date=today, end_date=today.replace(month=12, day=31),
        tuition_amount=Decimal("2500"),
    )
    nxt = TuitionPeriod.objects.create(
        name="Next", slug="pif-next",
        start_date=today.replace(year=today.year + 1, month=1, day=1),
        decision_due_date=today.replace(year=today.year + 1),
        end_date=today.replace(year=today.year + 1, month=12, day=31),
        tuition_amount=Decimal("3000"),
    )
    return cur, nxt


@pytest.mark.django_db
def test_pay_in_full_for_upcoming_period_binds_to_upcoming_not_current(
    client, two_periods, stub_stripe,
):
    from payments.models import Payment

    cur, nxt = two_periods
    u = User.objects.create_user(email="upcoming-pif@example.com", password="x")
    u.profile.role = "candidate"
    u.profile.save(update_fields=["role"])
    # A current-period enrollment exists too, to prove the upcoming POST
    # doesn't fall through to it.
    TuitionEnrollment.objects.create(
        user=u, tuition_period=cur, status=TuitionEnrollment.Status.COMMITTED,
    )
    TuitionEnrollment.objects.create(
        user=u, tuition_period=nxt, status=TuitionEnrollment.Status.COMMITTED,
    )
    client.force_login(u)

    resp = client.post(reverse("tuition_pay_in_full"), {"period": "pif-next"})
    assert resp.status_code == 302
    assert resp.url.startswith("https://stripe.test/")

    installment = TuitionInstallment.objects.get(enrollment__user=u, enrollment__tuition_period=nxt)
    assert installment.amount == nxt.tuition_amount
    payment = Payment.objects.get(user=u, payment_type=Payment.Type.TUITION)
    assert payment.tuition_installment_id == installment.id
    # Nothing minted against the current period.
    assert not TuitionInstallment.objects.filter(enrollment__tuition_period=cur).exists()


@pytest.mark.django_db
def test_setup_plan_for_upcoming_period_binds_to_upcoming_not_current(
    client, two_periods,
):
    cur, nxt = two_periods
    u = User.objects.create_user(email="upcoming-plan@example.com", password="x")
    u.profile.role = "candidate"
    u.profile.save(update_fields=["role"])
    TuitionEnrollment.objects.create(
        user=u, tuition_period=cur, status=TuitionEnrollment.Status.PAYMENT_PLAN,
    )
    TuitionEnrollment.objects.create(
        user=u, tuition_period=nxt, status=TuitionEnrollment.Status.PAYMENT_PLAN,
    )
    client.force_login(u)

    resp = client.post(reverse("tuition_setup_plan"), {
        "installment_count": "2", "period": "pif-next",
    })
    assert resp.status_code == 302

    installments = TuitionInstallment.objects.filter(
        enrollment__user=u, enrollment__tuition_period=nxt,
    ).order_by("sequence")
    assert installments.count() == 2
    assert sum(i.amount for i in installments) == nxt.tuition_amount
    assert not TuitionInstallment.objects.filter(enrollment__tuition_period=cur).exists()


# ---- The form says which year it is deciding (task #599) -------------------

@pytest.mark.django_db
def test_decision_form_names_its_academic_year():
    """Two decision forms sit on the Account tab, one per year. Neither may
    say 'this year': a member joining for the new year recorded a decision
    and paid $2,500 against the year that was ending (task #599)."""
    from datetime import date

    from payments.forms import TuitionDecisionForm

    period = make_period(TuitionPeriod, 
        name="AY 2026–2027", slug="ay-2026-2027-x",
        start_date=date(2026, 9, 1), decision_due_date=date(2026, 10, 31),
        end_date=date(2027, 8, 31), tuition_amount=Decimal("2500"),
    )
    form = TuitionDecisionForm(period=period)

    assert "AY 2026–2027" in form.fields["status"].label
    labels = [label for _value, label in form.fields["status"].choices]
    assert any("AY 2026–2027" in label for label in labels)
    assert not any("this year" in label for label in labels)


@pytest.mark.django_db
def test_decision_form_without_a_period_still_validates():
    """The POST path builds the form only to validate — no period, no labels."""
    from payments.forms import TuitionDecisionForm

    form = TuitionDecisionForm({"status": "skipping"})
    assert form.is_valid(), form.errors
