"""Seed the TuitionPeriod that contains today (M7.5).

Creates the current academic year's TuitionPeriod. (Originally this also
backfilled TuitionEnrollment rows from the legacy Profile.tuition_paying
boolean; that backfill ran once in production and the boolean has since
been dropped. The backfill is no longer needed.)
"""

from datetime import date
from decimal import Decimal

from django.db import migrations
from django.utils import timezone


def _current_ay_start_year(today):
    return today.year if today.month >= 9 else today.year - 1


def seed_period(apps, schema_editor):
    today = timezone.now().date()
    start_year = _current_ay_start_year(today)
    TuitionPeriod = apps.get_model("payments", "TuitionPeriod")
    TuitionPeriod.objects.update_or_create(
        slug=f"ay-{start_year}-{start_year + 1}-tuition",
        defaults={
            "name": f"AY {start_year}–{start_year + 1}",
            "start_date": date(start_year, 9, 1),
            "decision_due_date": date(start_year, 9, 30),
            "end_date": date(start_year + 1, 8, 31),
            "tuition_amount": Decimal("800.00"),
        },
    )


def unseed(apps, schema_editor):
    TuitionPeriod = apps.get_model("payments", "TuitionPeriod")
    today = timezone.now().date()
    start_year = _current_ay_start_year(today)
    TuitionPeriod.objects.filter(
        slug=f"ay-{start_year}-{start_year + 1}-tuition",
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("payments", "0005_tuitionperiod_alter_payment_payment_type_and_more")]
    operations = [migrations.RunPython(seed_period, unseed)]
