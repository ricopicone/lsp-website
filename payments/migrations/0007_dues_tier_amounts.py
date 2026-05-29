"""Convert DuesPeriod.dues_amount → three tier fields.

Schema change for billing dues by role: pre-candidates pay $50,
candidates $100, full Analysts/Scholars $150 (defaults — each period
can override). The old single ``dues_amount`` field is dropped after
the new fields are backfilled.

Backfill logic: every existing row gets the new per-role defaults
(50/100/150), regardless of what its old ``dues_amount`` was. Past
Payments are unaffected — they carry their own ``amount`` value.
"""

from decimal import Decimal

from django.db import migrations, models


def backfill_tiers(apps, schema_editor):
    DuesPeriod = apps.get_model("payments", "DuesPeriod")
    for p in DuesPeriod.objects.all():
        p.dues_amount_pre_candidate = Decimal("50.00")
        p.dues_amount_candidate     = Decimal("100.00")
        p.dues_amount_analyst       = Decimal("150.00")
        p.save(update_fields=(
            "dues_amount_pre_candidate",
            "dues_amount_candidate",
            "dues_amount_analyst",
        ))


def unbackfill(apps, schema_editor):
    # No-op — old single field was already dropped at this point in the
    # forward migration, and we don't try to recover the original values.
    pass


class Migration(migrations.Migration):
    dependencies = [("payments", "0006_seed_initial_tuition_period")]

    operations = [
        # Step 1: add the three new fields with placeholder defaults so the
        # NOT NULL constraint is satisfied. We'll backfill real values next.
        migrations.AddField(
            model_name="duesperiod",
            name="dues_amount_pre_candidate",
            field=models.DecimalField(
                max_digits=8, decimal_places=2, default=Decimal("50.00"),
                help_text="Amount owed by pre-candidates (analyst or scholar track).",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="duesperiod",
            name="dues_amount_candidate",
            field=models.DecimalField(
                max_digits=8, decimal_places=2, default=Decimal("100.00"),
                help_text="Amount owed by candidates (analyst or scholar track).",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="duesperiod",
            name="dues_amount_analyst",
            field=models.DecimalField(
                max_digits=8, decimal_places=2, default=Decimal("150.00"),
                help_text="Amount owed by full Analysts and Scholars.",
            ),
            preserve_default=False,
        ),
        # Step 2: backfill real values (idempotent — just sets the defaults).
        migrations.RunPython(backfill_tiers, unbackfill),
        # Step 3: drop the old single field.
        migrations.RemoveField(model_name="duesperiod", name="dues_amount"),
    ]
