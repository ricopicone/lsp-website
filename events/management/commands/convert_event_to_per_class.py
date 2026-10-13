"""Move an event, and everyone registered for it, to per-class billing.

The one route past the billing-mode lock (task #811), written for #810: a
seminar sold as a whole-seminar place for $25 that was meant to be $25 a
class. In place, with no refunds and no re-registering:

- the event becomes per-class at ``--price`` (``25`` or ``10-40``), billing
  classes that end on or after ``--bill-from``;
- each active registration gets a per-class rate (its code's terms read per
  class, else the price), ``quoted_amount`` 0, and stays enrolled;
- its whole-seminar charge is voided, so whatever it paid becomes credit that
  the ledger sweeps onto its first billed classes;
- a staff note on each, and a notice to each member.

Refuses while any registration is on a payment plan or any code on the event
carries installments: those need a person to decide, not this command.

    manage.py convert_event_to_per_class beyond-principle --price 25 \\
        --bill-from 2026-10-13 --dry-run
"""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from events import per_class
from events.models import Event
from events.price_spec import PriceSpec, apply_to_event, from_event, label
from registrations.models import Registration


def _price(raw: str, *, tuition_covers: bool) -> PriceSpec:
    try:
        if "-" in raw:
            low, high = (Decimal(p) for p in raw.split("-", 1))
            if low > high:
                raise CommandError("--price: the minimum can't exceed the maximum.")
            return PriceSpec(sliding_min=low, sliding_max=high,
                             tuition_covers=tuition_covers, per_class=True)
        return PriceSpec(amount=Decimal(raw), tuition_covers=tuition_covers,
                         per_class=True)
    except InvalidOperation as exc:
        raise CommandError(f"--price: {raw!r} isn't an amount or a range.") from exc


class Command(BaseCommand):
    help = "Convert an event and its registrations to per-class billing (task #811)."

    def add_arguments(self, parser):
        parser.add_argument("slug")
        parser.add_argument("--price", required=True,
                            help="Per-class price: 25, or a sliding range 10-40.")
        parser.add_argument("--bill-from", required=True,
                            help="YYYY-MM-DD; classes ending before this are not billed.")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        from payments.charges import void_registration_charge
        from payments.registration_plans import is_on_plan

        event = Event.objects.filter(slug=opts["slug"]).first()
        if event is None:
            raise CommandError(f"No event {opts['slug']!r}.")
        current = from_event(event)
        if current is None:
            raise CommandError(
                f"{event.slug} has more than one price; it can't be converted here."
            )
        try:
            bill_from = datetime.strptime(opts["bill_from"], "%Y-%m-%d").date()
        except ValueError as exc:
            raise CommandError("--bill-from must be YYYY-MM-DD.") from exc
        since = timezone.make_aware(datetime.combine(bill_from, time.min))
        spec = _price(opts["price"], tuition_covers=current.tuition_covers)

        regs = list(
            event.registrations
            .exclude(status__in=(Registration.Status.CANCELLED,
                                 Registration.Status.REFUNDED,
                                 Registration.Status.DECLINED))
            .select_related("user", "price_tier", "pricing_code")
            .order_by("created_at")
        )
        problems = [f"registration {r.pk} ({r.user.email}) is on a payment plan"
                    for r in regs if is_on_plan(r)]
        problems += [f"code {c.code} carries {c.installments} installments"
                     for c in event.pricing_codes.filter(installments__gt=1)]
        if problems:
            raise CommandError("Refusing to convert:\n  " + "\n  ".join(problems))

        dry = opts["dry_run"]
        self.stdout.write(
            f"{event.title}: {label(current)} -> {label(spec)}; "
            f"billing classes ending from {bill_from}."
        )

        with transaction.atomic():
            apply_to_event(event, spec, force=True)
            event.per_class_since = since
            event.save(update_fields=("per_class_since",))
            plan = []
            for reg in regs:
                reg.refresh_from_db()
                rate = per_class.converted_rate(reg)
                paid = reg.settled_amount
                plan.append((reg, rate, paid))
            for reg, rate, paid in plan:
                code = f" code {reg.pricing_code.code}" if reg.pricing_code_id else ""
                self.stdout.write(
                    f"  #{reg.pk} {reg.user.email}: {reg.get_status_display()}, "
                    f"quoted ${reg.quoted_amount}{code}, paid ${paid} -> "
                    f"${rate}/class; ${paid} becomes class credit"
                )
            if dry:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("Dry run: nothing saved."))
                return
            stamp = timezone.localdate().isoformat()
            for reg, rate, paid in plan:
                was = reg.quoted_amount
                reg.per_class_rate = rate
                reg.quoted_amount = Decimal("0")
                reg.quoted_explanation = (
                    f"Per class attended: ${rate} per class (converted from "
                    f"whole-seminar billing)."
                )
                if reg.status == Registration.Status.AWAITING_PAYMENT:
                    reg.status = Registration.Status.PAID
                reg.staff_notes = (
                    f"{reg.staff_notes}\n[{stamp}] Converted to per-class billing "
                    f"(task #811): was ${was} for the whole seminar; now ${rate} "
                    f"per class from {bill_from}. ${paid} already paid stays as "
                    "credit toward classes."
                ).strip()
                reg.save(update_fields=("per_class_rate", "quoted_amount",
                                        "quoted_explanation", "status",
                                        "staff_notes"))
                void_registration_charge(
                    reg, "Converted to per-class billing; payments become class credit.",
                )

        from payments import notifications as notify_payments
        from payments.stripe_sync import expire_open_sessions

        for reg, rate, paid in plan:
            expire_open_sessions(reg, reason="Converted to per-class billing.")
            notify_payments.converted_to_per_class(reg, paid=paid, since=bill_from)
        self.stdout.write(self.style.SUCCESS(
            f"Converted {event.title} and {len(plan)} registration(s)."
        ))
