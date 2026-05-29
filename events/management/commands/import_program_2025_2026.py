"""Seed the 2025-2026 academic year program from the Wix /seminars2025-2026 page.

One-shot management command (M12). Re-runnable; idempotent on (slug).
"""

from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from events.models import Event

# (first, last) for faculty names — matched against existing User accounts.
SEMINARS = [
    {
        "title": "Psychoanalytic Training in the School of Lacan - Part 7",
        "slug":  "psychoanalytic-training-2025-26-part-7",
        "faculty": [("Marcelo", "Estrada")],
        "start_date": date(2025, 9, 1),
        "end_date":   date(2026, 6, 30),
        "description": (
            "Dates and times: 5:30–8:00pm Pacific Time, last two Thursdays "
            "each month, September 2025 to June 2026; no classes in "
            "December 2025.\n\n"
            "Fee: $500 or School Tuition.\n\n"
            "Contact: Marcelo Estrada, marcelo.estrada@gmail.com."
        ),
    },
    {
        "title": "Four Lessons of Psychoanalysis",
        "slug":  "four-lessons-of-psychoanalysis-2025-26",
        "faculty": [("Robert", "Beshara")],
        "start_date": date(2025, 9, 4),
        "end_date":   date(2025, 9, 25),
        "description": (
            "Dates and times: 09/04, 09/11, 09/18, 09/25; 5–7pm Pacific Time.\n\n"
            "Fee: Donation to the School encouraged.\n\n"
            "Contact: besharaster@gmail.com."
        ),
    },
    {
        "title": "Reading Lacan's Seminar Book VIII: Transference",
        "slug":  "reading-seminar-viii-2025-26",
        "faculty": [("Yang", "Yu"), ("Cissy", "Hong Zhou")],
        "start_date": date(2025, 9, 1),
        "end_date":   date(2026, 5, 31),
        "description": (
            "Dates and times: 8:30–11:00am, second and fourth Wednesdays each "
            "month, September to May (Beijing time, break in December and "
            "February).\n\n"
            "Fee: US $400 or School Tuition.\n\n"
            "Contact: celavieglove@126.com; cissyhongzhou@126.com."
        ),
    },
    {
        "title": (
            "Lacan Seminars XXIII and XXIV (1975–'77): On love, unknown knowing "
            "and the failure that takes flight"
        ),
        "slug":  "lacan-seminars-xxiii-xxiv-2025-26",
        "faculty": [("Benjamin", "Davidson")],
        "start_date": date(2026, 1, 7),
        "end_date":   date(2026, 6, 30),
        "description": (
            "Dates and times: online, biweekly Wednesdays 5–7pm Pacific Time, "
            "beginning 7 January 2026.\n\n"
            "Fee: Free of charge (voluntary donation to LSP encouraged).\n\n"
            "Contact: benjamdavidson@me.com."
        ),
    },
    {
        "title": "Intersubjectivity, Otherness and the (Irreducible) Position of analyst",
        "slug":  "intersubjectivity-otherness-position-2025-26",
        "faculty": [("Ruonan", "Liu")],
        "start_date": date(2025, 9, 1),
        "end_date":   date(2026, 4, 30),
        "description": (
            "Dates and times: 8:30–11:00am, the fourth Saturday of every "
            "month (Beijing Time), September to April; no sessions in February.\n\n"
            "Fee: 2000 Yuan (RMB) / US $300 or School Tuition.\n\n"
            "Contact: immanuelliu006@gmail.com."
        ),
    },
    {
        "title": "Secretaries to the Psychotic Subject – Seminar III",
        "slug":  "secretaries-psychotic-subject-2025-26",
        "faculty": [("Casey", "Butcher")],
        "start_date": date(2026, 1, 6),
        "end_date":   date(2026, 5, 31),
        "description": (
            "Dates and times: 1st and 3rd Tuesday of the month at 8:00pm EST, "
            "January through May 2026.\n\n"
            "Fee: $150 or School Tuition.\n\n"
            "Contact: butcher.casey@gmail.com."
        ),
    },
    {
        "title": "Introduction to the Big Other: The closing portion of Seminar II",
        "slug":  "introduction-big-other-2025-26",
        "faculty": [("Casey", "Butcher")],
        "start_date": date(2025, 9, 2),
        "end_date":   date(2025, 12, 31),
        "description": (
            "Dates and times: 1st and 3rd Tuesday of the month at 8pm EST, "
            "September through December 2025.\n\n"
            "Fee: $150 or School Tuition.\n\n"
            "Contact: butcher.casey@gmail.com."
        ),
    },
    {
        "title": "Graphing Desire, Writing Dreams",
        "slug":  "graphing-desire-writing-dreams-2025-26",
        "faculty": [("Diana", "Cuello")],
        "start_date": date(2025, 9, 5),
        "end_date":   date(2026, 5, 31),
        "description": (
            "Dates and times: monthly, September to May, 1st Fridays, "
            "12–2pm Eastern Standard Time.\n\n"
            "Fee: $500 or School Tuition.\n\n"
            "Note: CE credits are available for this seminar (2 per meeting).\n\n"
            "Contact: Diana Cuello, dianacuellophd@gmail.com."
        ),
    },
    {
        "title": (
            "The work of the letter in psychoanalysis: Freud's letters, "
            "Lacan's return to Freud, speech and writing in the clinic and "
            "School of psychoanalysis"
        ),
        "slug":  "work-of-the-letter-2025-26",
        "faculty": [("Christopher", "Meyer")],
        "start_date": date(2025, 9, 27),
        "end_date":   date(2026, 6, 27),
        "description": (
            "Dates and times: every 4th Saturday of the month except December, "
            "27 September 2025 through 27 June 2026, 10am–12 noon Pacific "
            "Standard Time.\n\n"
            "Fee: $60 per session / $40 students, or School Tuition.\n\n"
            "Contact: Christopher Meyer, PhD; (323) 930-9662; cmeyerwoeswar@gmail.com."
        ),
    },
    {
        "title": "Lacanian Clinical Practice — Dream, Symptom, Fantasy: a Clinical Cases Seminar",
        "slug":  "lacanian-clinical-practice-2025-26",
        "faculty": [("Christopher", "Meyer")],
        "start_date": date(2025, 10, 14),
        "end_date":   date(2026, 6, 9),
        "description": (
            "Dates and times: second and fourth Tuesdays of the month, "
            "14 October 2025 through 9 June 2026, 7–8:20pm Pacific Time. "
            "Break from December until classes resume January 13; no class "
            "April 8; classes resume April 22.\n\n"
            "Fee: $40 per meeting or School Tuition.\n\n"
            "Contact: Christopher Meyer, PhD; (323) 930-9662; cmeyerwoeswar@gmail.com."
        ),
    },
    {
        "title": "Introduction to Lacan: Basic Concepts",
        "slug":  "intro-to-lacan-basic-concepts-2025-26",
        "faculty": [("Marcelo", "Estrada"), ("Diana", "Dopchiz de Martin")],
        "start_date": date(2026, 1, 31),
        "end_date":   date(2026, 2, 7),
        "description": (
            "Dates and times: Saturday 31 January 2026 and Saturday 7 February "
            "2026, 10am–12pm Pacific Time.\n\n"
            "Fee: Donation to the school.\n\n"
            "Contact: Marcelo Estrada, marcelo.estrada@gmail.com; and "
            "Diana Dopchiz de Martin, ddmartinmft@gmail.com."
        ),
    },
]


def _find_user(first: str, last: str) -> User | None:
    qs = User.objects.filter(first_name__iexact=first, last_name__iexact=last)
    if qs.exists():
        return qs.first()
    qs = User.objects.filter(last_name__iexact=last)
    if qs.count() == 1:
        return qs.first()
    return None


class Command(BaseCommand):
    help = "Import the 2025-2026 academic year seminar program from the Wix site."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--publish",
            action="store_true",
            help="Mark imported events as published=True so they appear on /program/.",
        )

    def handle(self, *args, dry_run: bool, publish: bool, **opts):
        report = {"created": 0, "updated": 0, "skipped": 0, "unresolved_faculty": []}

        with transaction.atomic():
            for s in SEMINARS:
                faculty: list[User] = []
                missing = []
                for first, last in s["faculty"]:
                    u = _find_user(first, last)
                    if u:
                        faculty.append(u)
                    else:
                        missing.append(f"{first} {last}")
                if missing:
                    report["unresolved_faculty"].append((s["title"], missing))
                    self.stderr.write(self.style.WARNING(
                        f"  {s['title']}: unresolved faculty {missing}"
                    ))

                defaults = {
                    "title":       s["title"],
                    "description": s["description"],
                    "event_type":  Event.Type.SEMINAR,
                    "format":      Event.Format.ONLINE,
                    "start_date":  s["start_date"],
                    "end_date":    s["end_date"],
                    "published":   publish,
                    "status":      Event.Status.OPEN if publish else Event.Status.DRAFT,
                }
                event, created = Event.objects.update_or_create(
                    slug=s["slug"], defaults=defaults,
                )
                event.faculty.set(faculty)
                report["created" if created else "updated"] += 1
                self.stdout.write(
                    f"  {'created' if created else 'updated'}: {event.slug} "
                    f"({len(faculty)} faculty)"
                )

            if dry_run:
                transaction.set_rollback(True)

        prefix = "Would " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}create {report['created']}, update {report['updated']}. "
            f"{len(report['unresolved_faculty'])} title(s) had unresolved faculty."
        ))
