"""The provenance hover appears on the treasurer tables (task #435)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from payments.models import DuesPeriod, Payment


@pytest.fixture
def current_period(db):
    period = DuesPeriod.current()
    if period is not None:
        return period
    today = timezone.now().date()
    return DuesPeriod.objects.create(
        name="Test AY", slug="test-ay",
        start_date=today - timedelta(days=60),
        due_date=today - timedelta(days=30),
        end_date=today + timedelta(days=300),
        dues_amount_pre_candidate=Decimal("50.00"),
        dues_amount_candidate=Decimal("100.00"),
        dues_amount_analyst=Decimal("150.00"),
    )


@pytest.fixture
def treasurer(db):
    u = User.objects.create_user(email="treas@x.test", password="x")
    u.is_staff = True
    u.save()
    return u


def _imported_payment(user, ptype=Payment.Type.TUITION, **extra):
    return Payment.objects.create(
        user=user, payment_type=ptype, amount="500.00",
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        source="imported",
        notes="[tz-import:tuition-24-25#1] | method unrecorded in ledger",
        **extra,
    )


@pytest.mark.django_db
def test_member_detail_shows_provenance_hover(client, treasurer):
    member = User.objects.create_user(email="member@x.test", password="x")
    _imported_payment(member)
    client.force_login(treasurer)
    resp = client.get(
        reverse("treasurer_member_detail", args=[member.id]),
        SERVER_NAME="localhost",
    )
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "data-prov-trigger" in body
    assert "Treasurer ledger ref · tuition-24-25#1" in body
    assert "method unrecorded in ledger" in body


@pytest.mark.django_db
def test_payments_tab_shows_provenance_hover(client, treasurer):
    member = User.objects.create_user(email="m2@x.test", password="x")
    _imported_payment(member)
    client.force_login(treasurer)
    resp = client.get(reverse("treasurer_payments"), SERVER_NAME="localhost")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "data-prov-trigger" in body
    assert "Treasurer ledger ref · tuition-24-25#1" in body


@pytest.mark.django_db
def test_member_statement_dues_row_gets_hover(client, treasurer, current_period):
    """The old Dues-tab badge hover now lives on the member's unified
    statement (task #439) — same provenance popover, new surface."""
    member = User.objects.create_user(email="m3@x.test", password="x")
    Payment.objects.create(
        user=member, payment_type=Payment.Type.DUES, amount="100.00",
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        dues_period=current_period, source="imported",
        notes="[tz-import:dues-25-26#17] | method unrecorded in ledger",
    )
    client.force_login(treasurer)
    resp = client.get(
        reverse("treasurer_member_detail", args=[member.id]), SERVER_NAME="localhost",
    )
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "data-prov-trigger" in body
    assert "Treasurer ledger ref · dues-25-26#17" in body
