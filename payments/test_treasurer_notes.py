"""Treasurer notes on charges and payments — append-only, attributed,
treasurer-only (task #439)."""

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
    u = User.objects.create_user(email="trn@x.test", password="x", is_staff=True)
    client.force_login(u)
    return u


def _member(email):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = "candidate"
    u.profile.save()
    return u


def test_payment_note_appends_attributed_line(client, treasurer):
    m = _member("nt1@x.test")
    p = Payment.objects.create(
        user=m, payment_type=Payment.Type.DUES, amount=Decimal("100"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        notes="existing line")
    resp = client.post(reverse("treasurer_payment_note", args=[p.id]),
                       {"note": "Likely duplicate of the Stripe charge."})
    assert resp.status_code == 302
    p.refresh_from_db()
    assert p.notes.startswith("existing line\n")
    assert "Note by treasurer trn@x.test" in p.notes
    assert "Likely duplicate of the Stripe charge." in p.notes


def test_charge_note_appends_without_freezing_sync(client, treasurer):
    m = _member("nt2@x.test")
    c = Charge.objects.create(
        user=m, category=Charge.Category.DUES, amount=Decimal("100"),
        effective_date=date(2025, 9, 1))
    client.post(reverse("treasurer_charge_note", args=[c.id]),
                {"note": "Member disputes this year."})
    c.refresh_from_db()
    assert "Note by treasurer trn@x.test" in c.notes
    assert "Member disputes this year." in c.notes
    assert c.staff_adjusted is False   # a comment must not freeze the sync


def test_empty_note_refused(client, treasurer):
    m = _member("nt3@x.test")
    p = Payment.objects.create(
        user=m, payment_type=Payment.Type.DUES, amount=Decimal("100"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE)
    client.post(reverse("treasurer_payment_note", args=[p.id]), {"note": "  "})
    p.refresh_from_db()
    assert p.notes == ""


def test_note_endpoints_require_staff(client):
    m = _member("nt4@x.test")
    p = Payment.objects.create(
        user=m, payment_type=Payment.Type.DUES, amount=Decimal("100"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE)
    client.force_login(m)
    resp = client.post(reverse("treasurer_payment_note", args=[p.id]),
                       {"note": "nope"})
    assert resp.status_code in (302, 403)
    p.refresh_from_db()
    assert "nope" not in p.notes


def test_note_modals_render_on_both_pages(client, treasurer):
    m = _member("nt5@x.test")
    Payment.objects.create(
        user=m, payment_type=Payment.Type.DUES, amount=Decimal("100"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE)
    Charge.objects.create(
        user=m, category=Charge.Category.DUES, amount=Decimal("100"),
        effective_date=date(2025, 9, 1))
    for url in (reverse("treasurer_payments"),
                reverse("treasurer_member_detail", args=[m.id])):
        content = client.get(url).content.decode()
        assert 'id="note-' in content
        assert "Add note" in content
