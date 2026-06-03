"""Treat tuition non-payment as a decision to skip the year.

Policy (set by the school): if a student didn't pay tuition for an academic
year, assume they chose to skip it. This command applies that to existing data:

* **Flip** every ``TuitionEnrollment`` that has no successful tuition payment
  to ``SKIPPING`` — across all academic years. Students who paid anything
  (paid-in-full or a partial payment-plan amount) are left untouched.
* **Create** ``SKIPPING`` rows for in-training students who have no enrollment
  at all — the current period by default, plus any past period named in
  ``--backfill-roster-for``. Creating rows needs a population to assume *about*;
  for the current year that's the live in-training roster, and for a named past
  year we deliberately proxy that same roster (assume today's in-training
  students were in-training then too). Past years not named are only flipped,
  never fabricated.

Dry-run by default; pass ``--commit`` to write. Idempotent (already-skipping
rows and already-recorded students are no-ops), so it's safe to re-run.

Example — backfill AY 2024-25 skips from the current roster::

    manage.py assume_skip_when_unpaid --commit \\
        --backfill-roster-for ay-2024-2025-tuition
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import Profile, Source, User
from payments.models import Payment, TuitionEnrollment, TuitionPeriod


class Command(BaseCommand):
    help = "Set tuition status to Skipping for students who didn't pay (dry-run unless --commit)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit", action="store_true",
            help="Actually write changes. Without it, dry-run only.",
        )
        parser.add_argument(
            "--backfill-roster-for", nargs="*", default=[], metavar="SLUG",
            help=(
                "Past TuitionPeriod slug(s) for which to ALSO create Skipping rows "
                "for the current in-training roster (a deliberate proxy: assume "
                "today's in-training students were in-training that year too). "
                "Students who already have an enrollment that year are untouched."
            ),
        )

    def handle(self, *args, **options):
        commit = options["commit"]
        backfill_slugs = set(options["backfill_roster_for"])
        current = TuitionPeriod.current()
        note = f"[assume-skip {timezone.now().date()}] no tuition payment on record"
        proxy_note = (
            f"[assume-skip {timezone.now().date()}] no enrollment on record; "
            "skip assumed (roster proxied from current in-training students)"
        )

        flipped = created = 0
        with transaction.atomic():
            sid = transaction.savepoint()
            for period in TuitionPeriod.objects.order_by("-start_date"):
                is_current = current is not None and period.id == current.id
                do_backfill = is_current or period.slug in backfill_slugs

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
                        e.source = Source.ASSUMED
                        e.notes = (e.notes + "\n" + note).strip() if e.notes else note
                        e.save(update_fields=["status", "source", "notes"])

                period_created = 0
                if do_backfill:
                    decided_ids = set(
                        TuitionEnrollment.objects.filter(tuition_period=period)
                        .values_list("user_id", flat=True)
                    )
                    undecided = User.objects.filter(
                        is_active=True,
                        profile__standing=Profile.Standing.ACTIVE,
                        profile__role__in=Profile.IN_TRAINING_ROLES,
                    ).exclude(id__in=decided_ids)
                    row_note = note if is_current else proxy_note
                    for u in undecided:
                        period_created += 1
                        if commit:
                            TuitionEnrollment.objects.create(
                                user=u, tuition_period=period,
                                status=TuitionEnrollment.Status.SKIPPING,
                                source=Source.ASSUMED,
                                notes=row_note,
                            )

                flipped += period_flipped
                created += period_created
                msg = f"{period.name}: flip {period_flipped} unpaid enrollment(s) → Skipping"
                if do_backfill:
                    msg += f", create {period_created} skip row(s) for undecided"
                self.stdout.write(msg)

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
