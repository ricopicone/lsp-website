"""Correct provenance on Stripe-imported payments.

Stripe-imported charges (notes ``[stripe-import:…]``) were stamped with
``source=IMPORTED`` — whose label is "Imported from treasurer ledger" — or
leaked to the ``STAFF`` default. Reclassify them to the new ``STRIPE``
("Imported from Stripe") source, and move the STAFF-defaulted provisional
charges to ``ASSUMED`` so they read correctly and re-enter the Reconcile queue.
Treasurer-ledger rows (``[tz-import:…]``) and genuine staff entries are untouched.

Idempotent — safe to re-run. Uses the shared helper so live imports and this
backfill stay in lockstep.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from payments.stripe_import import reclassify_stripe_sources

    Payment = apps.get_model("payments", "Payment")
    reclassify_stripe_sources(Payment)


def backwards(apps, schema_editor):
    # STRIPE is a new value; map it back to IMPORTED. The STAFF→ASSUMED move is
    # not reversed (ASSUMED is the correct state and other rows share it).
    Payment = apps.get_model("payments", "Payment")
    Payment.objects.filter(
        notes__startswith="[stripe-import:", source="stripe"
    ).update(source="imported")


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0014_alter_payment_source_alter_tuitionenrollment_source"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
