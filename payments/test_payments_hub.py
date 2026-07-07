"""Tests for the member Payments hub (task #354)."""

import pytest
from django.urls import reverse

from accounts.models import User
from payments.models import Payment, Receipt


def _paid(user=None, email="", ptype=Payment.Type.DONATION, amount="50.00"):
    p = Payment.objects.create(
        user=user, email=email, payment_type=ptype,
        amount=amount, status=Payment.Status.SUCCEEDED,
    )
    Receipt.create_for_payment(p)
    return p


@pytest.mark.django_db
def test_owner_can_download_receipt(client):
    u = User.objects.create_user(email="owner@x.test", password="x")
    p = _paid(user=u)
    client.force_login(u)
    resp = client.get(reverse("payments:receipt", args=[p.pk]), SERVER_NAME="localhost")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/plain")
    assert p.receipt.receipt_number.encode() in resp.content


@pytest.mark.django_db
def test_non_owner_gets_404(client):
    owner = User.objects.create_user(email="o@x.test")
    other = User.objects.create_user(email="x@x.test", password="x")
    p = _paid(user=owner)
    client.force_login(other)
    resp = client.get(reverse("payments:receipt", args=[p.pk]), SERVER_NAME="localhost")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_index_requires_login(client):
    resp = client.get(reverse("payments:index"), SERVER_NAME="localhost")
    assert resp.status_code in (301, 302)


@pytest.mark.django_db
def test_index_lists_only_own_payments(client):
    me = User.objects.create_user(email="me@x.test", password="x")
    other = User.objects.create_user(email="other@x.test")
    mine = _paid(user=me, amount="50.00")
    _paid(user=other, amount="99.00")
    client.force_login(me)
    body = client.get(reverse("payments:index"), SERVER_NAME="localhost").content.decode()
    assert mine.receipt.receipt_number in body
    assert "99.00" not in body


@pytest.mark.django_db
def test_index_has_dues_tuition_donate_links(client):
    me = User.objects.create_user(email="links@x.test", password="x")
    client.force_login(me)
    body = client.get(reverse("payments:index"), SERVER_NAME="localhost").content.decode()
    assert reverse("dues") in body
    assert reverse("donate") in body
    assert "/formation/?tab=tuition" in body
