"""Wipe intake-survey submissions and the records they generated.

For re-testing the survey on a clean slate: deletes every ``MemberIntakeSurvey``
and the ``source=SELF_REPORTED`` rows the survey creates (membership tenures,
tuition enrollments, dues payments). Only the survey generates SELF_REPORTED
data, so this fully undoes its effect without touching imported/staff records.

Dry-run by default; ``--commit`` to delete.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import MemberIntakeSurvey, MembershipTenure, Source
from payments.models import Payment, TuitionEnrollment


class Command(BaseCommand):
    help = "Delete intake surveys + the SELF_REPORTED records they generated."

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true",
                            help="Actually delete (default: dry-run preview).")

    def handle(self, *args, **opts):
        surveys = MemberIntakeSurvey.objects.count()
        tenures = MembershipTenure.objects.filter(source=Source.SELF_REPORTED)
        enrollments = TuitionEnrollment.objects.filter(source=Source.SELF_REPORTED)
        dues = Payment.objects.filter(
            source=Source.SELF_REPORTED, payment_type=Payment.Type.DUES,
        )
        self.stdout.write(
            f"surveys: {surveys}\n"
            f"self-reported tenures: {tenures.count()}\n"
            f"self-reported tuition enrollments: {enrollments.count()}\n"
            f"self-reported dues payments: {dues.count()}"
        )
        if not opts["commit"]:
            self.stdout.write(self.style.WARNING(
                "Dry run — nothing deleted. Re-run with --commit."
            ))
            return
        with transaction.atomic():
            dues.delete()
            enrollments.delete()
            tenures.delete()
            MemberIntakeSurvey.objects.all().delete()
        self.stdout.write(self.style.SUCCESS("Survey data reset."))
