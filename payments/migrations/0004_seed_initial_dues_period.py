"""Seed the DuesPeriod that contains today (the current academic year).

The AY starts Sep 1: if today is on/after Sep 1, the current AY is
``year–year+1``; else it's ``year-1–year``. Idempotent on slug.
"""

from datetime import date
from decimal import Decimal

from django.db import migrations
from django.utils import timezone


def _current_ay_start_year(today):
    return today.year if today.month >= 9 else today.year - 1


def seed_initial_period(apps, schema_editor):
    today = timezone.now().date()
    start_year = _current_ay_start_year(today)
    DuesPeriod = apps.get_model("payments", "DuesPeriod")
    DuesPeriod.objects.update_or_create(
        slug=f"ay-{start_year}-{start_year + 1}",
        defaults={
            "name": f"AY {start_year}–{start_year + 1}",
            "start_date": date(start_year, 9, 1),
            "due_date": date(start_year, 10, 1),
            "end_date": date(start_year + 1, 8, 31),
            "dues_amount": Decimal("100.00"),
        },
    )


def unseed_initial_period(apps, schema_editor):
    DuesPeriod = apps.get_model("payments", "DuesPeriod")
    today = timezone.now().date()
    start_year = _current_ay_start_year(today)
    DuesPeriod.objects.filter(
        slug=f"ay-{start_year}-{start_year + 1}",
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("payments", "0003_duesperiod_payment_dues_period_duesreminder")]
    operations = [migrations.RunPython(seed_initial_period, unseed_initial_period)]
