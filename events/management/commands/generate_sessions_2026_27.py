"""Bulk-generate Session rows for the 2026-2027 seminars.

The 15 seminars were imported with date/time descriptions in their
``Event.description`` but no ``Session`` rows, so the unified calendar
(/calendar/) shows them as empty. This command hand-encodes each
seminar's recurrence pattern and creates the Session rows.

All times stored in the project TIME_ZONE (America/Los_Angeles). For
Eastern Time events, the hour was converted to PT (ET − 3 hours).
For Beijing Time events, PT = Beijing − 15 hours (using the standard
PDT/Beijing offset; the small DST drift is negligible for calendar
display).

One-shot. Re-runnable: --clear empties the seminar's existing sessions
first. Idempotent slugs.
"""
# ruff: noqa: E501

from __future__ import annotations

from datetime import date, time, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

from events.models import Event, Session
from events.scheduling import (
    generate_explicit,
    generate_monthly_ordinal,
    generate_weekly,
)


def biweekly_dates(start: date, end: date, weekday: int) -> list[date]:
    """Every-other-week dates between start and end on the given weekday.

    ``weekday`` is Python's date.weekday() value (Mon=0..Sun=6). The
    start date is the first session; we add 14 days each step.
    """
    # Snap to the first occurrence of ``weekday`` on/after start.
    delta = (weekday - start.weekday()) % 7
    first = start + timedelta(days=delta)
    out = []
    d = first
    while d <= end:
        out.append(d)
        d += timedelta(days=14)
    return out


# Encoded as a list of dicts so each entry is independently editable.
# Each dict produces sessions via either generate_weekly,
# generate_monthly_ordinal, or generate_explicit + an explicit dates list.
SCHEDULES = [
    # 1. Das Unbehagen — Thursdays 5-7 PT, weekly for 5 sessions Oct 1.
    {
        "slug": "das-unbehagen-2026-27",
        "kind": "weekly",
        "weekdays": ["TH"], "start": date(2026, 10, 1), "end": date(2026, 10, 29),
        "start_time": time(17, 0), "end_time": time(19, 0),
        "location": "Online (Zoom)",
    },
    # 2. Workshop for a Clinic of Psychosis — 1st, 3rd, 5th Sat,
    #    Oct 3 2026 – Apr 17 2027, 9:00–11:30 PT. Skip Dec 19, Jan 2.
    {
        "slug": "workshop-clinic-of-psychosis-2026-27",
        "kind": "monthly",
        "weekdays": ["SA"], "weeks": [1, 3, 5],
        "start": date(2026, 10, 3), "end": date(2027, 4, 17),
        "start_time": time(9, 0), "end_time": time(11, 30),
        "location": "Online",
        "exclude": [date(2026, 12, 19), date(2027, 1, 2)],
    },
    # 3. Reading Lacan Seminar VIII (II) — 3rd & 4th Wed each month
    #    Sept–May, Beijing 9–11am = PT prior-day Tue evening 18:00.
    #    Beijing's 3rd Wed of month X is exactly the day after PT's
    #    3rd Tue of month X (Tue immediately before Wed; both in the
    #    same calendar month for any month). Stored as PT Tue 18:00-20:00
    #    so the calendar shows the session at the time PT participants
    #    actually join.
    {
        "slug": "reading-seminar-viii-ii-2026-27",
        "kind": "monthly",
        "weekdays": ["TU"], "weeks": [3, 4],
        "start": date(2026, 9, 1), "end": date(2027, 5, 31),
        "start_time": time(18, 0), "end_time": time(20, 0),
        # Calendar shows PT 18:00; actual PT time shifts to 17:00 during
        # PST (Nov-Mar) because Beijing doesn't observe DST. PT
        # participants should check their own conversion around DST.
        "location": "Online (Beijing 9-11am — PT time approx, check around DST)",
    },
    # 4. Sounding Out the Signifier — 1st Sat Sept 2026–May 2027,
    #    11am-1pm ET = 8am-10am PT. Per the docx: "January meeting will
    #    instead be held on 1/9/27 and May meeting will be held on 5/8/27."
    {
        "slug": "sounding-out-the-signifier-2026-27",
        "kind": "monthly",
        "weekdays": ["SA"], "weeks": [1],
        "start": date(2026, 9, 1), "end": date(2027, 5, 31),
        "start_time": time(8, 0), "end_time": time(10, 0),
        "location": "Philadelphia, PA (TBD)",
        "exclude": [date(2027, 1, 2), date(2027, 5, 1)],
        "extra_dates": [date(2027, 1, 9), date(2027, 5, 8)],
    },
    # 5. Secretaries to the Psychotic Subject – Seminar III continued.
    #    1st & 3rd Tue, Sept 2026 – May 2027, 8pm-10pm ET = 5pm-7pm PT.
    #    No 3rd Tue of December.
    {
        "slug": "secretaries-psychotic-subject-2026-27",
        "kind": "monthly",
        "weekdays": ["TU"], "weeks": [1, 3],
        "start": date(2026, 9, 1), "end": date(2027, 5, 31),
        "start_time": time(17, 0), "end_time": time(19, 0),
        "location": "Online (Zoom)",
        "exclude": [date(2026, 12, 15)],  # 3rd Tue Dec 2026
    },
    # 6. Graphing Desire, Writing Dreams — 1st Fri, Sept–May,
    #    12-2pm ET = 9-11am PT.
    {
        "slug": "graphing-desire-writing-dreams-2026-27",
        "kind": "monthly",
        "weekdays": ["FR"], "weeks": [1],
        "start": date(2026, 9, 1), "end": date(2027, 5, 31),
        "start_time": time(9, 0), "end_time": time(11, 0),
        "location": "Online (Zoom, by invitation)",
    },
    # 7. Logic of Phantasy — biweekly Wed starting Sept 9 2026,
    #    5–7pm PT. End assumed through May 2027.
    {
        "slug": "logic-of-phantasy-xiv-xv-2026-27",
        "kind": "biweekly",
        "weekday": 2,  # Wednesday
        "start": date(2026, 9, 9), "end": date(2027, 5, 26),
        "start_time": time(17, 0), "end_time": time(19, 0),
        "location": "Online",
    },
    # 8. Topology of Direction of Treatment — 2nd Sat each month,
    #    9am-11am PT, beginning Sept 12 2026, skipping November,
    #    running through May 2027.
    {
        "slug": "topology-direction-of-treatment-2026-27",
        "kind": "monthly",
        "weekdays": ["SA"], "weeks": [2],
        "start": date(2026, 9, 1), "end": date(2027, 5, 31),
        "start_time": time(9, 0), "end_time": time(11, 0),
        "location": "Online",
        "exclude": [date(2026, 11, 14)],  # skip November
    },
    # 9. Clinic of the Death Drives — 3rd Sun, Jan 2027 – Jun 2027,
    #    10am-12pm ET = 7am-9am PT.
    {
        "slug": "clinic-of-the-death-drives-2026-27",
        "kind": "monthly",
        "weekdays": ["SU"], "weeks": [3],
        "start": date(2027, 1, 1), "end": date(2027, 6, 30),
        "start_time": time(7, 0), "end_time": time(9, 0),
        "location": "Virtual (Zoom)",
    },
    # 10. Beyond Principle — every other Monday, 5-7pm PT,
    #     Sept 28 2026 – Jun 28 2027.
    {
        "slug": "beyond-principle-2026-27",
        "kind": "biweekly",
        "weekday": 0,  # Monday
        "start": date(2026, 9, 28), "end": date(2027, 6, 28),
        "start_time": time(17, 0), "end_time": time(19, 0),
        "location": "Virtual",
    },
    # 11. Analyst's Act and its Results — 4th Sat of Sept, Nov, Jan, Mar,
    #     May, Jun 2026-2027, 10am-12pm PT.
    {
        "slug": "analysts-act-and-its-results-2026-27",
        "kind": "explicit",
        "dates": [
            date(2026, 9, 26),  date(2026, 11, 28),
            date(2027, 1, 23),  date(2027, 3, 27),
            date(2027, 5, 22),  date(2027, 6, 26),
        ],
        "start_time": time(10, 0), "end_time": time(12, 0),
        "location": "Online (Zoom)",
    },
    # 12. Psychoanalysis in its Place and Time (LA) — Oct 24 2026,
    #     Feb 27 2027, Apr 24 2027, 10am-12pm PT.
    {
        "slug": "psychoanalysis-place-and-time-la-2026-27",
        "kind": "explicit",
        "dates": [date(2026, 10, 24), date(2027, 2, 27), date(2027, 4, 24)],
        "start_time": time(10, 0), "end_time": time(12, 0),
        "location": "TBD, mid-City Los Angeles, CA",
    },
    # 13. Lacanian Clinical Practice — 2nd and 4th Tue,
    #     Oct 13 2026 – Jun 8 2027, 7-8:20pm PT.
    #     Per docx: "break from December until classes resume January 12,
    #     and no class March 23." (Jan 12 = 2nd Tue Jan, so resume IS the
    #     first session of Jan — only the Dec sessions are skipped, plus
    #     March 23.)
    {
        "slug": "lacanian-clinical-practice-2026-27",
        "kind": "monthly",
        "weekdays": ["TU"], "weeks": [2, 4],
        "start": date(2026, 10, 13), "end": date(2027, 6, 8),
        "start_time": time(19, 0), "end_time": time(20, 20),
        "location": "Online (Zoom)",
        "exclude": [
            date(2026, 12, 8),  date(2026, 12, 22),  # December break
            date(2027, 3, 23),                        # no class March 23
        ],
    },
    # 14. Freud Reading Group — 2nd Sun starting Sept 13 2026
    #     ("Starting September 8th" in the doc; Sept 8 is a Tuesday — the
    #     2nd Sunday is Sept 13). 9-11am PT.
    {
        "slug": "freud-reading-group-2026-27",
        "kind": "monthly",
        "weekdays": ["SU"], "weeks": [2],
        "start": date(2026, 9, 1), "end": date(2027, 5, 31),
        "start_time": time(9, 0), "end_time": time(11, 0),
        "location": "Online (Zoom)",
    },
    # 15. Intro to Lacan — Feb 6, Feb 13 2027, 2-4pm PT.
    {
        "slug": "intro-to-lacan-basic-concepts-2026-27",
        "kind": "explicit",
        "dates": [date(2027, 2, 6), date(2027, 2, 13)],
        "start_time": time(14, 0), "end_time": time(16, 0),
        "location": "Online (Zoom)",
    },
]


def windows_for_schedule(s: dict):
    kind = s["kind"]
    if kind == "weekly":
        return generate_weekly(
            start_date=s["start"], end_date=s["end"],
            weekdays=s["weekdays"],
            start_time=s["start_time"], end_time=s["end_time"],
        )
    if kind == "monthly":
        return generate_monthly_ordinal(
            start_date=s["start"], end_date=s["end"],
            weekdays=s["weekdays"], week_positions=s["weeks"],
            start_time=s["start_time"], end_time=s["end_time"],
        )
    if kind == "explicit":
        return generate_explicit(
            dates=s["dates"],
            start_time=s["start_time"], end_time=s["end_time"],
        )
    if kind == "biweekly":
        return generate_explicit(
            dates=biweekly_dates(s["start"], s["end"], s["weekday"]),
            start_time=s["start_time"], end_time=s["end_time"],
        )
    raise ValueError(f"Unknown schedule kind: {kind!r}")


class Command(BaseCommand):
    help = "Generate Session rows for the 2026-2027 seminars (one-shot, re-runnable)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Print what would be created without saving.",
        )
        parser.add_argument(
            "--clear", action="store_true",
            help="Delete each seminar's existing sessions before creating new ones.",
        )

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        clear = opts["clear"]
        total_created = 0
        skipped_events = []

        for s in SCHEDULES:
            event = Event.objects.filter(slug=s["slug"]).first()
            if event is None:
                skipped_events.append(s["slug"])
                continue

            try:
                windows = windows_for_schedule(s)
            except ValueError as exc:
                self.stderr.write(f"{s['slug']}: pattern error — {exc}")
                continue

            exclude = set(s.get("exclude", ()))
            # Apply exclude on the date portion of each window.
            windows = [w for w in windows if w.start_at.date() not in exclude]

            # Append extra one-off dates (e.g. a moved meeting from the
            # standard pattern). Each gets the same start/end time as the
            # main pattern.
            extras = s.get("extra_dates", ())
            if extras:
                extras_windows = generate_explicit(
                    dates=list(extras),
                    start_time=s["start_time"], end_time=s["end_time"],
                )
                windows = sorted(
                    list(windows) + list(extras_windows),
                    key=lambda w: w.start_at,
                )

            verb = "would create" if dry else "create"
            self.stdout.write(f"\n{event.title}")
            self.stdout.write(f"  {verb} {len(windows)} session(s) at {s.get('location', '—')}")

            if dry:
                for w in windows[:3]:
                    self.stdout.write(f"    e.g. {w.start_at.isoformat()}")
                if len(windows) > 3:
                    self.stdout.write(f"    ... and {len(windows) - 3} more")
                total_created += len(windows)
                continue

            with transaction.atomic():
                if clear:
                    deleted, _ = event.sessions.all().delete()
                    if deleted:
                        self.stdout.write(f"    cleared {deleted} existing")
                next_seq = (
                    event.sessions.order_by("-sequence")
                    .values_list("sequence", flat=True).first() or 0
                )
                for i, w in enumerate(windows):
                    Session.objects.create(
                        event=event, title="",
                        start_at=w.start_at, end_at=w.end_at,
                        location=s.get("location", ""),
                        sequence=next_seq + i + 1,
                    )
                total_created += len(windows)

        verb_done = "Would create" if dry else "Created"
        self.stdout.write(self.style.SUCCESS(
            f"\n{verb_done} {total_created} session(s) across "
            f"{len(SCHEDULES) - len(skipped_events)} seminar(s)."
        ))
        if skipped_events:
            self.stdout.write("\nSkipped (no Event with slug):")
            for s in skipped_events:
                self.stdout.write(f"  - {s}")
