"""Provenance-source correctness for Stripe-imported payments (source-labeling fix)."""

import inspect

import pytest

from accounts.models import Source
from payments import stripe_import
from payments.models import Payment
from payments.stripe_import import reclassify_stripe_sources


@pytest.mark.django_db
def test_reclassify_stripe_import_sources():
    # Confidently-imported Stripe charge mislabeled as ledger import.
    a = Payment.objects.create(
        payment_type=Payment.Type.TUITION, amount="2500.00",
        status=Payment.Status.SUCCEEDED, method=Payment.Method.STRIPE,
        source=Source.IMPORTED, notes="[stripe-import:ch_A]",
    )
    # Provisional Stripe charge that leaked to the STAFF default.
    b = Payment.objects.create(
        payment_type=Payment.Type.TUITION, amount="1000.00",
        status=Payment.Status.SUCCEEDED, method=Payment.Method.STRIPE,
        source=Source.STAFF, notes="[stripe-import:ch_B] (provisional — confirm via survey)",
    )
    # A real treasurer-ledger row — must NOT be touched.
    c = Payment.objects.create(
        payment_type=Payment.Type.DUES, amount="100.00",
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        source=Source.IMPORTED, notes="[tz-import:dues-24-25#1]",
    )
    # A genuinely staff-entered non-import payment — must NOT be touched.
    d = Payment.objects.create(
        payment_type=Payment.Type.DONATION, amount="20.00",
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        source=Source.STAFF, notes="cash at the door",
    )

    n_stripe, n_assumed = reclassify_stripe_sources(Payment)
    assert (n_stripe, n_assumed) == (1, 1)

    for row in (a, b, c, d):
        row.refresh_from_db()
    assert a.source == Source.STRIPE
    assert b.source == Source.ASSUMED
    assert c.source == Source.IMPORTED   # ledger untouched
    assert d.source == Source.STAFF      # non-import untouched

    # Idempotent.
    assert reclassify_stripe_sources(Payment) == (0, 0)


def test_stripe_import_uses_stripe_source_for_confident_charges():
    """New non-provisional Stripe imports should be labeled STRIPE, not IMPORTED."""
    src = inspect.getsource(stripe_import.apply_plan)
    assert "Source.STRIPE" in src
    assert "Source.ASSUMED if plan.provisional else Source.IMPORTED" not in src
