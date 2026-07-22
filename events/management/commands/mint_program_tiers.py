"""Mint PriceTiers for the imported 2026-27 program (task #450).

The 2026-27 events were script-imported (not minted from PC proposals), so
none carry the PriceTier a proposal approval would have created. This command
translates each event's published fee note into one event-level tier, per the
pricing approved 2026-07-22:

- "$N or tuition"  -> fixed base N, covered by tuition.
- donation events  -> sliding from $0, suggested $100, covered.
- per-session fees -> fixed whole-term base (rate x session count, no sliding;
  revised 2026-07-22). A stated student rate becomes a second
  audience=student tier at student-rate x session count. The register flow
  only sells event-level tiers.

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
#:   ("per_session", rate, student_rate | None)  # base = rate x sessions, fixed
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
    # $25/class.
    "beyond-principle-2026-27": ("per_session", Decimal("25"), None),
    # $60/session, $40 students.
    "analysts-act-and-its-results-2026-27": ("per_session", Decimal("60"), Decimal("40")),
    "psychoanalysis-place-and-time-la-2026-27": ("per_session", Decimal("60"), Decimal("40")),
    # $40/meeting.
    "lacanian-clinical-practice-2026-27": ("per_session", Decimal("40"), None),
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
            sliding = kind == "donation"
            student_base = None
            if kind == "per_session":
                n = max(event.sessions.count(), 1)
                base = spec[1] * n
                if spec[2] is not None:
                    student_base = spec[2] * n
            else:  # fixed / donation
                base = spec[1]

            tiers = [(Audience.ALL, base)]
            if student_base is not None:
                tiers.append((Audience.STUDENT, student_base))
            label = ", ".join(
                f"{aud}=${amt}" for aud, amt in tiers
            ) + (", sliding from $0" if sliding else "")
            if opts["commit"]:
                for audience, amount in tiers:
                    PriceTier.objects.create(
                        event=event,
                        audience=audience,
                        base_amount=amount,
                        sliding_scale=sliding,
                        minimum_amount=Decimal("0"),
                        covered_by_tuition=True,
                    )
                created += 1
                self.stdout.write(self.style.SUCCESS(f"created {slug}: {label}"))
            else:
                created += 1
                self.stdout.write(f"would create {slug}: {label}")

        verb = "Created" if opts["commit"] else "Would create"
        self.stdout.write(
            f"{verb} {created}; skipped {skipped}; missing {missing}."
            + ("" if opts["commit"] else " Re-run with --commit to write.")
        )
