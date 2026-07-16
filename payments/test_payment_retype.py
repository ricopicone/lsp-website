"""Treasurer re-categorize (payment_type flip) — Payments tab + member
statement action (task #439)."""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import Source, User
from payments.models import DuesPeriod, Payment, TuitionInstallment, TuitionPeriod

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


@pytest.fixture
def member():
    u = User.objects.create_user(email="mb@x.test", password="x")
    u.profile.role = "candidate"
    u.profile.save()
    return u


def _tuition_period(**overrides):
    kwargs = dict(
        name="AY 2026-2027 T", slug="t-2026-retype",
        start_date=date(2026, 9, 1), end_date=date(2027, 8, 31),
        decision_due_date=date(2026, 8, 31), tuition_amount=Decimal("2000"))
    kwargs.update(overrides)
    return TuitionPeriod.objects.create(**kwargs)


def _dues_period(**overrides):
    kwargs = dict(
        name="AY 2026-2027", slug="ay-2026-retype",
        start_date=date(2026, 9, 1), due_date=date(2026, 9, 30),
        end_date=date(2027, 8, 31),
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"),
        dues_amount_analyst=Decimal("150"))
    kwargs.update(overrides)
    return DuesPeriod.objects.create(**kwargs)


def test_retype_tuition_to_registration_clears_fks_and_notes(client, treasurer, member):
    period = _tuition_period()
    from payments.models import TuitionEnrollment
    enr = TuitionEnrollment.objects.create(
        user=member, tuition_period=period,
        status=TuitionEnrollment.Status.PAID_IN_FULL)
    installment = TuitionInstallment.objects.create(
        enrollment=enr, sequence=1, due_date=period.decision_due_date,
        amount=Decimal("2000"))
    payment = Payment.objects.create(
        payment_type=Payment.Type.TUITION, user=member, amount=Decimal("2000"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        tuition_period=period, tuition_installment=installment)

    resp = client.post(
        reverse("treasurer_payment_retype", args=[payment.id]),
        {"payment_type": "registration"})
    assert resp.status_code == 302
    payment.refresh_from_db()
    assert payment.payment_type == Payment.Type.REGISTRATION
    assert payment.tuition_period_id is None
    assert payment.tuition_installment_id is None
    assert payment.dues_period_id is None
    assert "Tuition" in payment.notes
    assert "Registration" in payment.notes
    assert f"unlinked installment #{installment.id}" in payment.notes
    assert "tr3@x.test" in payment.notes
    assert payment.source == Source.VERIFIED


def test_retype_to_dues_binds_period(client, treasurer, member):
    from payments import ledger
    period = _dues_period()
    payment = Payment.objects.create(
        payment_type=Payment.Type.DONATION, user=member, amount=Decimal("100"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE)

    before = ledger.member_account(member)["paid"]
    resp = client.post(
        reverse("treasurer_payment_retype", args=[payment.id]),
        {"payment_type": "dues", "dues_period": str(period.id)})
    assert resp.status_code == 302
    payment.refresh_from_db()
    assert payment.payment_type == Payment.Type.DUES
    assert payment.dues_period_id == period.id
    after = ledger.member_account(member)["paid"]
    assert after - before == Decimal("100")


def test_retype_defaults_period_from_payment_date(client, treasurer, member):
    period = _dues_period()
    payment = Payment.objects.create(
        payment_type=Payment.Type.DONATION, user=member, amount=Decimal("100"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        paid_at=timezone_aware(date(2026, 10, 1)))

    resp = client.post(
        reverse("treasurer_payment_retype", args=[payment.id]),
        {"payment_type": "dues"})
    assert resp.status_code == 302
    payment.refresh_from_db()
    assert payment.dues_period_id == period.id


def timezone_aware(d):
    import datetime

    from django.utils import timezone
    return timezone.make_aware(datetime.datetime(d.year, d.month, d.day, 12, 0))


def test_noop_retype_refused(client, treasurer, member):
    payment = Payment.objects.create(
        payment_type=Payment.Type.DONATION, user=member, amount=Decimal("100"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        notes="original note")

    resp = client.post(
        reverse("treasurer_payment_retype", args=[payment.id]),
        {"payment_type": "donation"})
    assert resp.status_code == 302
    payment.refresh_from_db()
    assert payment.notes == "original note"
    from django.contrib.messages import get_messages
    msgs = [str(m) for m in get_messages(resp.wsgi_request)]
    assert any("already" in m.lower() for m in msgs)


def test_next_honored(client, treasurer, member):
    payment = Payment.objects.create(
        payment_type=Payment.Type.DONATION, user=member, amount=Decimal("100"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE)
    next_url = reverse("treasurer_member_detail", args=[member.id])
    resp = client.post(
        reverse("treasurer_payment_retype", args=[payment.id]),
        {"payment_type": "registration", "next": next_url})
    assert resp.status_code == 302
    assert resp.url == next_url


def test_requires_staff(client, member):
    payment = Payment.objects.create(
        payment_type=Payment.Type.DONATION, user=member, amount=Decimal("100"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE)
    other = User.objects.create_user(email="notstaff@x.test", password="x")
    client.force_login(other)
    resp = client.post(
        reverse("treasurer_payment_retype", args=[payment.id]),
        {"payment_type": "registration"})
    assert resp.status_code in (302, 403)
    payment.refresh_from_db()
    assert payment.payment_type == Payment.Type.DONATION
