"""The provenance hover appears on the treasurer tables (task #435)."""

import pytest
from django.urls import reverse

from accounts.models import User
from payments.models import Payment


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
