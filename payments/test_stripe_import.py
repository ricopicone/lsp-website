"""Tests for the historical Stripe importer (logic only — no network)."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone as dt_timezone
from decimal import Decimal

import pytest

from accounts.models import Source, User
from payments.management.commands.import_stripe_payments import Command
from payments.models import Payment
from payments.stripe_import import (
    apply_plan,
    classify_type,
    normalize_charge,
    plan_charges,
    tag_for,
)

pytestmark = pytest.mark.django_db

# 1700000000 → 2023-11-14 UTC
TS = 1700000000
DAY = datetime.fromtimestamp(TS, tz=dt_timezone.utc)


def _charge(cid="ch_1", amount=15000, email="ann@x.test", name="Ann Lee",
            pi="pi_1", status="succeeded", paid=True, refunded=False,
            amount_refunded=0, description="", created=TS):
    return {
        "id": cid, "amount": amount, "currency": "usd", "created": created,
        "status": status, "paid": paid, "refunded": refunded,
        "amount_refunded": amount_refunded,
        "billing_details": {"email": email, "name": name},
        "receipt_email": None, "customer": None,
        "payment_intent": pi, "description": description,
    }


def _user(email, first="Ann", last="Lee"):
    return User.objects.create_user(email=email, password="x",
                                    first_name=first, last_name=last)


def _plan(charges, *, sessions=None, default_type=None, allow_overlaps=False):
    rows = [normalize_charge(c, sessions_by_pi=sessions or {}) for c in charges]
    ctx = Command().build_context(default_type)
    return plan_charges(rows, ctx, allow_overlaps=allow_overlaps)


# ---- normalization & classification ---------------------------------------

def test_normalize_charge():
    row = normalize_charge(_charge(amount=15000, description="Dues 2023"))
    assert row.amount == Decimal("150.00")
    assert row.currency == "usd"
    assert row.created == DAY
    assert row.email == "ann@x.test" and row.name == "Ann Lee"
    assert row.payment_intent == "pi_1"


def test_normalize_links_session():
    sessions = {"pi_1": {"id": "cs_9", "payment_intent": "pi_1",
                         "metadata": {"payment_id": "42", "payment_type": "registration"}}}
    row = normalize_charge(_charge(), sessions_by_pi=sessions)
    assert row.checkout_session_id == "cs_9"
    assert row.session_payment_id == "42"
    assert row.session_payment_type == "registration"


def test_classify_type():
    valid = set(Payment.Type.values)
    assert classify_type(normalize_charge(_charge(description="Annual dues")), valid) == "dues"
    assert classify_type(normalize_charge(_charge(description="Tuition 1st")), valid) == "tuition"
    assert classify_type(normalize_charge(_charge(description="Gift to LSP")), valid) == "donation"
    assert classify_type(normalize_charge(_charge(description="opaque")), valid) is None


# ---- create bucket --------------------------------------------------------

def test_create_matched_by_email():
    _user("ann@x.test")
    plans = _plan([_charge(description="Annual dues")])
    assert plans[0].action == "create"
    assert plans[0].member_match == "email"
    apply_plan(plans)
    p = Payment.objects.get(stripe_payment_intent_id="pi_1")
    assert p.amount == Decimal("150.00")
    assert p.status == Payment.Status.SUCCEEDED
    assert p.method == Payment.Method.STRIPE
    assert p.source == Source.IMPORTED
    assert p.payment_type == Payment.Type.DUES
    assert p.user is not None
    assert p.paid_at == DAY
    assert tag_for("ch_1") in p.notes


def test_create_unmatched_member():
    plans = _plan([_charge(email="nobody@x.test", name="Zzz Nobody",
                           description="donation")])
    assert plans[0].action == "create_unmatched"
    apply_plan(plans)
    p = Payment.objects.get(stripe_payment_intent_id="pi_1")
    assert p.user_id is None and p.email == "nobody@x.test"
    assert "unmatched payer" in p.notes


def test_needs_type_when_uninferable():
    _user("ann@x.test")
    plans = _plan([_charge(description="mystery")])
    assert plans[0].action == "needs_type"
    apply_plan(plans)
    assert not Payment.objects.filter(stripe_payment_intent_id="pi_1").exists()


def test_default_type_sweeps_unknown():
    _user("ann@x.test")
    plans = _plan([_charge(description="mystery")], default_type="donation")
    assert plans[0].action == "create"
    apply_plan(plans)
    p = Payment.objects.get(stripe_payment_intent_id="pi_1")
    assert p.payment_type == Payment.Type.DONATION
    assert "type defaulted" in p.notes


def test_skip_failed_charge():
    _user("ann@x.test")
    plans = _plan([_charge(status="failed", paid=False)])
    assert plans[0].action == "skip_not_paid"


# ---- reconcile bucket -----------------------------------------------------

def test_reconcile_succeeded_site_payment():
    u = _user("ann@x.test")
    Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, user=u, amount=Decimal("150.00"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.STRIPE,
        stripe_payment_intent_id="pi_1", source=Source.STAFF,
    )
    plans = _plan([_charge()])
    assert plans[0].action == "reconcile"
    apply_plan(plans)
    p = Payment.objects.get(stripe_payment_intent_id="pi_1")
    assert p.source == Source.VERIFIED  # confirmed by Stripe
    assert tag_for("ch_1") in p.notes


def test_reconcile_flag_pending_site_payment():
    u = _user("ann@x.test")
    Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, user=u, amount=Decimal("150.00"),
        status=Payment.Status.PENDING, method=Payment.Method.STRIPE,
        stripe_payment_intent_id="pi_1", source=Source.STAFF,
    )
    plans = _plan([_charge()])
    assert plans[0].action == "reconcile_flag"
    apply_plan(plans)
    p = Payment.objects.get(stripe_payment_intent_id="pi_1")
    assert p.status == Payment.Status.PENDING  # not silently flipped
    assert tag_for("ch_1") in p.notes


def test_reconcile_by_session_metadata():
    u = _user("ann@x.test")
    existing = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, user=u, amount=Decimal("150.00"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.STRIPE,
        source=Source.STAFF,
    )
    sessions = {"pi_1": {"id": "cs_1", "payment_intent": "pi_1",
                         "metadata": {"payment_id": str(existing.pk)}}}
    plans = _plan([_charge()], sessions=sessions)
    assert plans[0].action == "reconcile"
    assert plans[0].existing_payment_id == existing.pk


# ---- overlap & idempotency ------------------------------------------------

def _offline_ledger_row(user):
    return Payment.objects.create(
        payment_type=Payment.Type.DUES, user=user, amount=Decimal("150.00"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        source=Source.IMPORTED, paid_at=DAY,
    )


def test_overlap_with_ledger_skipped_then_allowed():
    u = _user("ann@x.test")
    _offline_ledger_row(u)
    plans = _plan([_charge(description="dues")])
    assert plans[0].action == "overlap"
    apply_plan(plans)
    assert not Payment.objects.filter(stripe_payment_intent_id="pi_1").exists()
    # Forcing it creates the row anyway.
    plans = _plan([_charge(description="dues")], allow_overlaps=True)
    assert plans[0].action == "create"


def test_idempotent_rerun_skips():
    _user("ann@x.test")
    plans = _plan([_charge(description="dues")])
    apply_plan(plans)
    # Re-plan: the tag is now in the DB, so the charge is skipped.
    plans2 = _plan([_charge(description="dues")])
    assert plans2[0].action == "skip_already"
    apply_plan(plans2)
    assert Payment.objects.filter(stripe_payment_intent_id="pi_1").count() == 1
