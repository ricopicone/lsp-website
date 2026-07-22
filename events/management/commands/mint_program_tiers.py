"""Mint PriceTiers for the imported 2026-27 program (task #450).

The 2026-27 events were script-imported (not minted from PC proposals), so
none carry the PriceTier a proposal approval would have created. This command
translates each event's published fee note into one event-level tier, per the
pricing approved 2026-07-22:

- "$N or tuition"  -> fixed base N, covered by tuition.
- donation events  -> sliding from $0, suggested $100, covered.
- per-session fees -> whole-term base (rate x session count), sliding with a
  one-session floor so partial attenders self-adjust ($0 floor where the note
  says none turned away). The register flow only sells event-level tiers.

Dry-run by default; ``--commit`` writes. Idempotent: events that already have
any tier are skipped, so re-runs (and later proposal-minted tiers) are safe.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand

from events.models import Audience, Event, PriceTier

#: slug -> (kind, args)
#:   ("fixed", amount)
#:   ("donation", suggested)
#:   ("per_session", rate, floor)   # base = rate x sessions; floor is absolute
TIER_SPECS: dict[str, tuple] = {
    "workshop-clinic-of-psychosis-2026-27": ("fixed", Decimal("500")),
    "sounding-out-the-signifier-2026-27": ("fixed", Decimal("500")),
    "graphing-desire-writing-dreams-2026-27": ("fixed", Decimal("500")),
    "reading-seminar-viii-ii-2026-27": ("fixed", Decimal("400")),
    "freud-reading-group-2026-27": ("fixed", Decimal("250")),
    "secretaries-psychotic-subject-2026-27": ("fixed", Decimal("200")),
    "topology-direction-of-treatment-2026-27": ("fixed", Decimal("200")),
    "intro-to-lacan-basic-concepts-2026-27": ("fixed", Decimal("50")),
    "das-unbehagen-2026-27": ("donation", Decimal("100")),
    "clinic-of-the-death-drives-2026-27": ("donation", Decimal("100")),
    "logic-of-phantasy-xiv-xv-2026-27": ("donation", Decimal("100")),
    # $25/class, none turned away.
    "beyond-principle-2026-27": ("per_session", Decimal("25"), Decimal("0")),
    # $60/session ($40 students) — floor of one meeting at the student rate.
    "analysts-act-and-its-results-2026-27": ("per_session", Decimal("60"), Decimal("40")),
    "psychoanalysis-place-and-time-la-2026-27": ("per_session", Decimal("60"), Decimal("40")),
    # $40/meeting — floor of one meeting.
    "lacanian-clinical-practice-2026-27": ("per_session", Decimal("40"), Decimal("40")),
}


class Command(BaseCommand):
    help = "Mint PriceTiers for the imported 2026-27 program events (dry-run unless --commit)."

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true", help="Write the tiers.")

    def handle(self, *args, **opts):
        created = skipped = missing = 0
        for slug, spec in TIER_SPECS.items():
            event = Event.objects.filter(slug=slug).first()
            if event is None:
                missing += 1
                self.stderr.write(f"missing event: {slug}")
                continue
            if event.price_tiers.exists():
                skipped += 1
                self.stdout.write(f"skip (has tiers): {slug}")
                continue

            kind = spec[0]
            if kind == "fixed":
                base, sliding, minimum = spec[1], False, Decimal("0")
            elif kind == "donation":
                base, sliding, minimum = spec[1], True, Decimal("0")
            else:  # per_session
                rate, minimum = spec[1], spec[2]
                base, sliding = rate * max(event.sessions.count(), 1), True

            label = f"{slug}: base ${base}" + (
                f", sliding from ${minimum}" if sliding else ""
            )
            if opts["commit"]:
                PriceTier.objects.create(
                    event=event,
                    audience=Audience.ALL,
                    base_amount=base,
                    sliding_scale=sliding,
                    minimum_amount=minimum,
                    covered_by_tuition=True,
                )
                created += 1
                self.stdout.write(self.style.SUCCESS(f"created {label}"))
            else:
                created += 1
                self.stdout.write(f"would create {label}")

        verb = "Created" if opts["commit"] else "Would create"
        self.stdout.write(
            f"{verb} {created}; skipped {skipped}; missing {missing}."
            + ("" if opts["commit"] else " Re-run with --commit to write.")
        )
