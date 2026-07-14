"""The 'No payer' attribution queue on the treasurer Reconcile tab."""

import pytest
from django.urls import reverse

from accounts.models import Source, User
from payments.models import Payment


@pytest.fixture
def treasurer(db):
    u = User.objects.create_user(email="np-treas@x.test", password="x")
    u.is_staff = True
    u.save()
    return u


def _no_payer(amount="100.00", ptype=Payment.Type.DUES, payer="Jane Roe"):
    return Payment.objects.create(
        payment_type=ptype, amount=amount, status=Payment.Status.SUCCEEDED,
        method=Payment.Method.STRIPE, source=Source.STRIPE, user=None,
        notes=f"[stripe-import:ch_X{amount}] (unmatched payer: {payer})",
    )


@pytest.mark.django_db
def test_queue_lists_only_stripe_no_user(client, treasurer):
    inq = _no_payer()
    Payment.objects.create(  # reconcile queue, not no-payer
        payment_type=Payment.Type.TUITION, amount="200.00",
        status=Payment.Status.SUCCEEDED, method=Payment.Method.STRIPE,
        source=Source.ASSUMED, notes="[stripe-import:ch_Y] (unmatched payer: Bob)",
    )
    member = User.objects.create_user(email="m@x.test", password="x")
    linked = _no_payer(amount="55.00")
    linked.user = member
    linked.save()
    client.force_login(treasurer)
    resp = client.get(reverse("treasurer_reconcile"), SERVER_NAME="localhost")
    body = resp.content.decode()
    assert "Jane Roe" in body                 # the no-payer charge
    assert f'value="{inq.pk}"' in body
    assert f'value="{linked.pk}"' not in body  # member-linked excluded


@pytest.mark.django_db
def test_assign_to_member(client, treasurer):
    p = _no_payer()
    member = User.objects.create_user(
        email="jane@x.test", password="x", first_name="Jane", last_name="Roe")
    client.force_login(treasurer)
    resp = client.post(reverse("treasurer_reconcile"), {
        "form": "no_payer", "action": "save", "payment_ids": [p.pk],
        "payment_type": Payment.Type.DUES, "assign_user": "jane@x.test",
    }, SERVER_NAME="localhost")
    assert resp.status_code == 302
    p.refresh_from_db()
    assert p.user_id == member.id
    assert p.source == Source.VERIFIED
    assert p.payment_type == Payment.Type.DUES


@pytest.mark.django_db
def test_anonymous_donation(client, treasurer):
    p = _no_payer(ptype=Payment.Type.TUITION)
    client.force_login(treasurer)
    client.post(reverse("treasurer_reconcile"), {
        "form": "no_payer", "action": "anonymous", "payment_ids": [p.pk],
    }, SERVER_NAME="localhost")
    p.refresh_from_db()
    assert p.payment_type == Payment.Type.DONATION
    assert p.user_id is None
    assert p.source == Source.VERIFIED


@pytest.mark.django_db
def test_named_payer_keeps_unlinked(client, treasurer):
    p = _no_payer(payer="Jane Roe")
    client.force_login(treasurer)
    client.post(reverse("treasurer_reconcile"), {
        "form": "no_payer", "action": "save", "payment_ids": [p.pk],
        "payment_type": Payment.Type.DONATION, "assign_user": "",
        "payer_name": "Jane Q. Roe Foundation",
    }, SERVER_NAME="localhost")
    p.refresh_from_db()
    assert p.user_id is None
    assert p.source == Source.VERIFIED
    assert p.payment_type == Payment.Type.DONATION
    assert "Jane Q. Roe Foundation" in p.notes


@pytest.mark.django_db
def test_constrained_to_queue(client, treasurer):
    assumed = Payment.objects.create(
        payment_type=Payment.Type.TUITION, amount="200.00",
        status=Payment.Status.SUCCEEDED, method=Payment.Method.STRIPE,
        source=Source.ASSUMED, notes="[stripe-import:ch_Z]",
    )
    client.force_login(treasurer)
    client.post(reverse("treasurer_reconcile"), {
        "form": "no_payer", "action": "anonymous", "payment_ids": [assumed.pk],
    }, SERVER_NAME="localhost")
    assumed.refresh_from_db()
    assert assumed.source == Source.ASSUMED       # untouched
    assert assumed.payment_type == Payment.Type.TUITION
