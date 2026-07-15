"""Member account page: statement + add/adjust/waive/void + record payment (task #439)."""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import User
from payments.models import Charge, DuesPeriod, Payment, TuitionPeriod

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_periods():
    TuitionPeriod.objects.all().delete()
    DuesPeriod.objects.all().delete()


@pytest.fixture
def treasurer(client):
    u = User.objects.create_user(email="tr2@x.test", password="x", is_staff=True)
    client.force_login(u)
    return u


@pytest.fixture
def member():
    u = User.objects.create_user(email="ma@x.test", password="x")
    u.profile.role = "candidate"
    u.profile.save()
    return u


def test_member_page_shows_statement_and_tiles(client, treasurer, member):
    Charge.objects.create(
        user=member, category=Charge.Category.DUES, amount=Decimal("100"),
        effective_date=date(2026, 9, 1))
    resp = client.get(reverse("treasurer_member_detail", args=[member.id]))
    assert resp.status_code == 200
    assert b"Statement" in resp.content
    assert resp.context["acct"]["owes"] == Decimal("100")


def test_add_charge(client, treasurer, member):
    resp = client.post(
        reverse("treasurer_charge_add", args=[member.id]),
        {"category": "dues", "amount": "75", "effective_date": "2026-09-01",
         "note": "Prorated half-year."})
    assert resp.status_code == 302
    c = Charge.objects.get(user=member)
    assert c.amount == Decimal("75")
    assert c.staff_adjusted is True
    assert "Prorated half-year." in c.notes
    assert "tr2@x.test" in c.notes


def test_add_charge_rejects_bad_amount(client, treasurer, member):
    client.post(reverse("treasurer_charge_add", args=[member.id]),
                {"category": "dues", "amount": "-5", "effective_date": "2026-09-01"})
    assert Charge.objects.count() == 0


def test_waive_void_adjust_reopen(client, treasurer, member):
    c = Charge.objects.create(
        user=member, category=Charge.Category.DUES, amount=Decimal("100"),
        effective_date=date(2026, 9, 1))
    url = reverse("treasurer_charge_update", args=[c.id])
    client.post(url, {"action": "waive"})
    c.refresh_from_db()
    assert c.status == Charge.Status.WAIVED and c.staff_adjusted
    client.post(url, {"action": "reopen"})
    c.refresh_from_db()
    assert c.status == Charge.Status.OPEN
    client.post(url, {"action": "adjust", "amount": "80"})
    c.refresh_from_db()
    assert c.amount == Decimal("80")
    client.post(url, {"action": "void"})
    c.refresh_from_db()
    assert c.status == Charge.Status.VOID
    assert c.notes.count("tr2@x.test") == 4  # every action audited


def test_record_offline_dues_payment(client, treasurer, member):
    from django.utils import timezone
    y = timezone.now().date().year
    start = y if timezone.now().date().month >= 9 else y - 1
    DuesPeriod.objects.create(
        name=f"AY {start}-{start + 1}", slug=f"ay-{start}-{start + 1}",
        start_date=date(start, 9, 1), due_date=date(start, 9, 30),
        end_date=date(start + 1, 8, 31),
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"),
        dues_amount_analyst=Decimal("150"))
    resp = client.post(
        reverse("treasurer_record_payment", args=[member.id]),
        {"category": "dues", "amount": "100"})
    assert resp.status_code == 302
    p = Payment.objects.get(user=member)
    assert p.status == Payment.Status.SUCCEEDED
    assert p.method == Payment.Method.OFFLINE
    assert p.dues_period is not None
    assert hasattr(p, "receipt")


def test_record_offline_tuition_payment_flips_enrollment(client, treasurer, member):
    from django.utils import timezone

    from payments.models import TuitionEnrollment
    y = timezone.now().date().year
    start = y if timezone.now().date().month >= 9 else y - 1
    TuitionPeriod.objects.create(
        name=f"AY {start}-{start + 1} T", slug=f"t-{start}",
        start_date=date(start, 9, 1), end_date=date(start + 1, 8, 31),
        decision_due_date=date(start, 8, 31), tuition_amount=Decimal("2000"))
    client.post(reverse("treasurer_record_payment", args=[member.id]),
                {"category": "tuition", "amount": "2000"})
    enr = TuitionEnrollment.objects.get(user=member)
    assert enr.status == TuitionEnrollment.Status.PAID_IN_FULL
