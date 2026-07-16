"""Assign/reassign payments to member accounts + Payer column (task #439)."""

from datetime import date, datetime
from datetime import timezone as tz
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import User
from payments import ledger
from payments.models import DuesPeriod, Payment, TuitionPeriod

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_periods():
    TuitionPeriod.objects.all().delete()
    DuesPeriod.objects.all().delete()


@pytest.fixture
def treasurer(client):
    u = User.objects.create_user(email="tra@x.test", password="x", is_staff=True)
    client.force_login(u)
    return u


def _member(email, first="Mem", last="Ber"):
    u = User.objects.create_user(email=email, password="x",
                                 first_name=first, last_name=last)
    u.profile.role = "candidate"
    u.profile.save()
    return u


def _payment(user=None, ptype=Payment.Type.DONATION, amount="100",
             email="", notes=""):
    p = Payment.objects.create(
        user=user, payment_type=ptype, amount=Decimal(amount),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.STRIPE,
        email=email, notes=notes)
    Payment.objects.filter(pk=p.pk).update(
        paid_at=datetime(2026, 6, 1, 12, tzinfo=tz.utc))
    p.refresh_from_db()
    return p


def test_assign_unlinked_payment(client, treasurer):
    target = _member("assignee@x.test", "Jane", "Doe")
    p = _payment(email="payer@somewhere.test")
    resp = client.post(
        reverse("treasurer_payment_assign", args=[p.id]),
        {"assign_user": f"Jane Doe ({target.email})",
         "next": "/treasurer/payments/"})
    assert resp.status_code == 302
    p.refresh_from_db()
    assert p.user_id == target.id
    assert p.source == "verified"
    assert "Assigned to assignee@x.test" in p.notes
    assert "payer@somewhere.test" in p.notes          # old payer recorded


def test_reassign_moves_money_between_accounts(client, treasurer):
    a = _member("a-acct@x.test", "Old", "Owner")
    b = _member("b-acct@x.test", "New", "Owner")
    p = _payment(user=a, ptype=Payment.Type.DUES)
    client.post(reverse("treasurer_payment_assign", args=[p.id]),
                {"assign_user": b.email})
    p.refresh_from_db()
    assert p.user_id == b.id
    assert "a-acct@x.test" in p.notes                 # old account recorded
    assert ledger.member_account(b)["paid"] == Decimal("100")
    assert ledger.member_account(a)["paid"] == Decimal("0")


def test_assign_refuses_registration_linked(client, treasurer):
    from events.models import Audience, Event, PriceTier
    from registrations.models import Registration
    m = _member("reg-owner@x.test")
    other = _member("other@x.test")
    event = Event.objects.create(title="X", slug="x",
                                 start_date=date(2026, 9, 1),
                                 end_date=date(2026, 12, 15))
    tier = PriceTier.objects.create(event=event, audience=Audience.ALL,
                                    base_amount=Decimal("60"))
    reg = Registration.objects.create(user=m, event=event, price_tier=tier,
                                      quoted_amount=Decimal("60"))
    p = Payment.objects.create(
        user=m, payment_type=Payment.Type.REGISTRATION, registration=reg,
        amount=Decimal("60"), status=Payment.Status.SUCCEEDED,
        method=Payment.Method.STRIPE)
    resp = client.post(reverse("treasurer_payment_assign", args=[p.id]),
                       {"assign_user": other.email})
    assert resp.status_code == 302
    p.refresh_from_db()
    assert p.user_id == m.id
    assert "Assigned" not in p.notes


def test_assign_unresolvable_member_is_refused(client, treasurer):
    p = _payment()
    client.post(reverse("treasurer_payment_assign", args=[p.id]),
                {"assign_user": "nobody@nowhere.test"})
    p.refresh_from_db()
    assert p.user_id is None
    assert "Assigned" not in p.notes


def test_payments_tab_payer_column(client, treasurer):
    linked = _member("linked@x.test", "Linda", "Linked")
    _payment(user=linked)
    _payment(notes="Imported from Stripe (unmatched payer: Jane Stripe)")
    _payment(email="only-email@x.test")
    resp = client.get(reverse("treasurer_payments"))
    content = resp.content.decode()
    assert "Payer" in content                          # renamed column
    assert "anonymous" not in content                  # gone
    assert "Linda Linked" in content
    assert "Jane Stripe" in content                    # parsed Stripe payer
    assert "only-email@x.test" in content              # email fallback
    assert "Assign" in content                         # per-row action


def test_retype_renders_as_modal_not_dropdown(client, treasurer):
    _payment()
    resp = client.get(reverse("treasurer_payments"))
    content = resp.content.decode()
    assert "<dialog" in content
    assert 'details class="dropdown"' not in content


def test_member_page_has_assign_and_modal(client, treasurer):
    m = _member("stmt@x.test")
    _payment(user=m)
    resp = client.get(reverse("treasurer_member_detail", args=[m.id]))
    content = resp.content.decode()
    assert "<dialog" in content
    assert "Assign" in content
