"""Overview tab: ledger tiles + consolidated needs-attention queue (task #439)."""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from payments.models import Charge, DuesPeriod, TuitionEnrollment, TuitionPeriod

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_periods():
    TuitionPeriod.objects.all().delete()
    DuesPeriod.objects.all().delete()


@pytest.fixture
def treasurer(client):
    u = User.objects.create_user(email="tr3@x.test", password="x", is_staff=True)
    client.force_login(u)
    return u


def _current_tuition_period():
    today = timezone.now().date()
    start = today.year if today.month >= 9 else today.year - 1
    return TuitionPeriod.objects.create(
        name=f"AY {start}-{start + 1} T", slug=f"t-{start}",
        start_date=date(start, 9, 1), end_date=date(start + 1, 8, 31),
        decision_due_date=date(start, 8, 31), tuition_amount=Decimal("2000"))


def test_overview_renders_with_ledger_numbers(client, treasurer):
    u = User.objects.create_user(email="ov@x.test", password="x")
    Charge.objects.create(user=u, category=Charge.Category.DUES,
                          amount=Decimal("100"), effective_date=date(2026, 9, 1))
    resp = client.get(reverse("treasurer"))
    assert resp.status_code == 200
    assert resp.context["total_outstanding"] == Decimal("100")
    assert resp.context["owing_count"] == 1


def test_attention_queue_lists_undecided_and_committed(client, treasurer):
    period = _current_tuition_period()
    undecided = User.objects.create_user(email="und@x.test", password="x")
    undecided.profile.role = "candidate"
    undecided.profile.save()
    committed = User.objects.create_user(email="com@x.test", password="x")
    committed.profile.role = "candidate"
    committed.profile.save()
    TuitionEnrollment.objects.create(
        user=committed, tuition_period=period,
        status=TuitionEnrollment.Status.COMMITTED, source="staff")
    resp = client.get(reverse("treasurer"))
    att = resp.context["attention"]
    assert undecided in att["undecided"]
    assert [e.user for e in att["committed_unpaid"]] == [committed]
