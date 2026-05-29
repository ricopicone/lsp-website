"""Seed the TuitionPeriod that contains today + backfill enrollments (M7.5).

Two operations:

1. Create the current academic year's TuitionPeriod.
2. Backfill ``TuitionEnrollment`` rows for every Profile whose legacy
   ``tuition_paying=True`` boolean was set — status=committed. Treasurer
   reconciles ahead of the September decision-due date.
"""

from datetime import date
from decimal import Decimal

from django.db import migrations
from django.utils import timezone


def _current_ay_start_year(today):
    return today.year if today.month >= 9 else today.year - 1


def seed_period_and_backfill(apps, schema_editor):
    today = timezone.now().date()
    start_year = _current_ay_start_year(today)
    TuitionPeriod = apps.get_model("payments", "TuitionPeriod")
    TuitionEnrollment = apps.get_model("payments", "TuitionEnrollment")
    Profile = apps.get_model("accounts", "Profile")

    period, _ = TuitionPeriod.objects.update_or_create(
        slug=f"ay-{start_year}-{start_year + 1}-tuition",
        defaults={
            "name": f"AY {start_year}–{start_year + 1}",
            "start_date": date(start_year, 9, 1),
            "decision_due_date": date(start_year, 9, 30),
            "end_date": date(start_year + 1, 8, 31),
            "tuition_amount": Decimal("800.00"),
        },
    )

    # Backfill: any Profile with legacy tuition_paying=True gets a
    # COMMITTED enrollment for this period.
    in_training = {
        "pre_candidate", "candidate",
        "pre_candidate_scholar", "candidate_scholar",
    }
    profiles = Profile.objects.filter(tuition_paying=True, role__in=in_training)
    for p in profiles:
        TuitionEnrollment.objects.update_or_create(
            user_id=p.user_id, tuition_period=period,
            defaults={"status": "committed"},
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
    operations = [migrations.RunPython(seed_period_and_backfill, unseed)]
