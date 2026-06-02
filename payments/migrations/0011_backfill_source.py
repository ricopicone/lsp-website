"""Backfill the new ``source`` provenance flag on existing rows.

New rows default to ``staff``; this tags the history we already created:
- Payments stamped ``[tz-import …]`` came from the treasurer ledger import.
- Remaining succeeded Stripe payments are real money → verified.
- Tuition enrollments noted ``[assume-skip …]`` were assumed; those
  "Backfilled from …" came from the ledger import.
Everything else keeps the ``staff`` default.
"""

from django.db import migrations

# Source choice values (kept as literals so the migration is stable).
IMPORTED = "imported"
VERIFIED = "verified"
ASSUMED = "assumed"


def backfill(apps, schema_editor):
    Payment = apps.get_model("payments", "Payment")
    TuitionEnrollment = apps.get_model("payments", "TuitionEnrollment")

    # Payments
    Payment.objects.filter(notes__contains="tz-import").update(source=IMPORTED)
    (
        Payment.objects.filter(method="stripe", status="succeeded")
        .exclude(notes__contains="tz-import")
        .update(source=VERIFIED)
    )

    # Tuition enrollments
    TuitionEnrollment.objects.filter(notes__contains="assume-skip").update(source=ASSUMED)
    (
        TuitionEnrollment.objects.filter(notes__contains="Backfilled from")
        .exclude(notes__contains="assume-skip")
        .update(source=IMPORTED)
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0010_payment_source_tuitionenrollment_source"),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
