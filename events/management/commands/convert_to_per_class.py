"""Move registrations onto per-class billing, in place (tasks #810/#811).

Written for #810: on a $500 whole-seminar event, faculty minted $25 fixed
codes meaning $25 a class, and four people were enrolled for the year. The
other registrants keep the seminar price; only the named registrations move:

- each gets a per-class rate (its code's terms read per class, else the
  tier's price) and ``quoted_amount`` 0, and stays enrolled;
- its whole-seminar charge is voided, so what it paid becomes credit that this
  registration's classes draw on first;
- only classes ending on or after ``--bill-from`` are recorded and billed;
- the code it used is marked per class, so the roster and the faculty's code
  list say so;
- a staff note on each, and a notice to each member.

Refuses a registration on a payment plan, or one already cancelled/refunded.

    manage.py convert_to_per_class --registration 252 --registration 254 \\
        --bill-from 2026-10-13 --dry-run
"""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from events import per_class
from registrations.models import Registration


class Command(BaseCommand):
    help = "Move registrations onto per-class billing (task #811)."

    def add_arguments(self, parser):
        parser.add_argument("--registration", type=int, action="append",
                            required=True, help="Registration id (repeat).")
        parser.add_argument("--bill-from", required=True,
                            help="YYYY-MM-DD; classes ending before this are not billed.")
        parser.add_argument("--rate", type=Decimal,
                            help="Per-class rate for all of them. Required for a "
                            "registration with no code, whose tier price is for "
                            "the whole seminar.")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        from payments.charges import void_registration_charge
        from payments.registration_plans import is_on_plan

        try:
            bill_from = datetime.strptime(opts["bill_from"], "%Y-%m-%d").date()
        except ValueError as exc:
            raise CommandError("--bill-from must be YYYY-MM-DD.") from exc
        since = timezone.make_aware(datetime.combine(bill_from, time.min))

        ids = opts["registration"]
        regs = list(
            Registration.objects.filter(pk__in=ids)
            .select_related("user", "event", "price_tier", "pricing_code")
            .order_by("pk")
        )
        missing = set(ids) - {r.pk for r in regs}
        problems = [f"registration {pk} doesn't exist" for pk in sorted(missing)]
        for r in regs:
            if r.is_per_class:
                problems.append(f"registration {r.pk} is already per class")
            if r.status not in (Registration.Status.PAID, Registration.Status.COMPED,
                                Registration.Status.AWAITING_PAYMENT,
                                Registration.Status.PENDING_APPROVAL):
                problems.append(f"registration {r.pk} is {r.get_status_display().lower()}")
            if is_on_plan(r):
                problems.append(f"registration {r.pk} is on a payment plan")
            if r.pricing_code_id and r.pricing_code.installments > 1:
                problems.append(f"registration {r.pk}'s code carries installments")
            if (opts["rate"] is None and not r.event.is_per_class
                    and r.pricing_code_id is None):
                problems.append(
                    f"registration {r.pk} has no code to take a per-class rate "
                    "from; pass --rate"
                )
        if problems:
            raise CommandError("Refusing to convert:\n  " + "\n  ".join(problems))

        plan = [
            (r, opts["rate"] if opts["rate"] is not None else per_class.converted_rate(r),
             r.settled_amount)
            for r in regs
        ]
        self.stdout.write(f"Billing classes ending from {bill_from}.")
        for reg, rate, paid in plan:
            code = f" code {reg.pricing_code.code}" if reg.pricing_code_id else ""
            self.stdout.write(
                f"  #{reg.pk} {reg.user.email} ({reg.event.title}): "
                f"{reg.get_status_display()}, quoted ${reg.quoted_amount}{code}, "
                f"paid ${paid} -> ${rate}/class; ${paid} becomes class credit"
            )
        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run: nothing saved."))
            return

        stamp = timezone.localdate().isoformat()
        with transaction.atomic():
            for reg, rate, paid in plan:
                was = reg.quoted_amount
                reg.per_class_rate = rate
                reg.per_class_since = since
                reg.quoted_amount = Decimal("0")
                reg.quoted_explanation = (
                    f"Per class attended: ${rate} per class (converted from "
                    "whole-seminar billing)."
                )
                if reg.status == Registration.Status.AWAITING_PAYMENT:
                    reg.status = Registration.Status.PAID
                reg.staff_notes = (
                    f"{reg.staff_notes}\n[{stamp}] Converted to per-class billing "
                    f"(task #811): was ${was} for the whole seminar; now ${rate} "
                    f"per class from {bill_from}. ${paid} already paid stays as "
                    "credit toward classes."
                ).strip()
                reg.save(update_fields=(
                    "per_class_rate", "per_class_since", "quoted_amount",
                    "quoted_explanation", "status", "staff_notes",
                ))
                void_registration_charge(
                    reg, "Converted to per-class billing; payments become class credit.",
                )
                if reg.pricing_code_id and not reg.pricing_code.per_class:
                    reg.pricing_code.per_class = True
                    reg.pricing_code.save(update_fields=("per_class",))

        from payments import notifications as notify_payments
        from payments.stripe_sync import expire_open_sessions

        for reg, _rate, paid in plan:
            expire_open_sessions(reg, reason="Converted to per-class billing.")
            notify_payments.converted_to_per_class(reg, paid=paid, since=bill_from)
        self.stdout.write(self.style.SUCCESS(f"Converted {len(plan)} registration(s)."))
