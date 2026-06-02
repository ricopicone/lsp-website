"""Treat tuition non-payment as a decision to skip the year.

Policy (set by the school): if a student didn't pay tuition for an academic
year, assume they chose to skip it. This command applies that to existing data:

* **Flip** every ``TuitionEnrollment`` that has no successful tuition payment
  to ``SKIPPING`` — across all academic years. Students who paid anything
  (paid-in-full or a partial payment-plan amount) are left untouched.
* **Create** ``SKIPPING`` rows for in-training students who have no enrollment
  at all — *current period only*, where the live in-training roster is the
  right population. Past years aren't fabricated: we don't know who was
  in-training then, so only their existing rows are flipped.

Dry-run by default; pass ``--commit`` to write. Idempotent (already-skipping
rows and already-recorded students are no-ops), so it's safe to re-run.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import Profile, User
from payments.models import Payment, TuitionEnrollment, TuitionPeriod


class Command(BaseCommand):
    help = "Set tuition status to Skipping for students who didn't pay (dry-run unless --commit)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit", action="store_true",
            help="Actually write changes. Without it, dry-run only.",
        )

    def handle(self, *args, **options):
        commit = options["commit"]
        current = TuitionPeriod.current()
        note = f"[assume-skip {timezone.now().date()}] no tuition payment on record"

        flipped = created = 0
        with transaction.atomic():
            sid = transaction.savepoint()
            for period in TuitionPeriod.objects.order_by("-start_date"):
                is_current = current is not None and period.id == current.id

                # Enrollment ids with at least one successful tuition payment.
                paid_enr_ids = {
                    row["tuition_installment__enrollment"]
                    for row in Payment.objects.filter(
                        payment_type=Payment.Type.TUITION,
                        status=Payment.Status.SUCCEEDED,
                        tuition_installment__enrollment__tuition_period=period,
                    ).values("tuition_installment__enrollment").distinct()
                    if row["tuition_installment__enrollment"] is not None
                }

                enrollments = list(
                    TuitionEnrollment.objects.filter(tuition_period=period)
                    .exclude(status=TuitionEnrollment.Status.SKIPPING)
                )
                period_flipped = 0
                for e in enrollments:
                    if e.id in paid_enr_ids:
                        continue  # they paid something — leave as-is
                    period_flipped += 1
                    if commit:
                        e.status = TuitionEnrollment.Status.SKIPPING
                        e.notes = (e.notes + "\n" + note).strip() if e.notes else note
                        e.save(update_fields=["status", "notes"])

                period_created = 0
                if is_current:
                    decided_ids = set(
                        TuitionEnrollment.objects.filter(tuition_period=period)
                        .values_list("user_id", flat=True)
                    )
                    undecided = User.objects.filter(
                        is_active=True, profile__role__in=Profile.IN_TRAINING_ROLES,
                    ).exclude(id__in=decided_ids)
                    for u in undecided:
                        period_created += 1
                        if commit:
                            TuitionEnrollment.objects.create(
                                user=u, tuition_period=period,
                                status=TuitionEnrollment.Status.SKIPPING,
                                notes=note,
                            )

                flipped += period_flipped
                created += period_created
                self.stdout.write(
                    f"{period.name}: flip {period_flipped} unpaid enrollment(s) → Skipping"
                    + (f", create {period_created} skip row(s) for undecided" if is_current else "")
                )

            if commit:
                transaction.savepoint_commit(sid)
                self.stdout.write(self.style.SUCCESS(
                    f"\nCOMMIT: {flipped} flipped, {created} created."
                ))
            else:
                transaction.savepoint_rollback(sid)
                self.stdout.write(self.style.NOTICE(
                    f"\nDRY-RUN: would flip {flipped}, create {created}. "
                    "Re-run with --commit to apply."
                ))
