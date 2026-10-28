"""Make the Scholarly Seminar Series' earlier talks events (task #851).

The series ran by email and Zoom from 2024, before the site took it over. Its
talks are listed here as Sheila Cavanagh, who created the series, sent them
(2026-10-27), and become ordinary events of type ``scholarly_seminar``: each
gets a page, lists itself on the series page and on /events/past/, and can
carry an abstract or a recording later.

Create-only and idempotent: a talk whose slug already exists is left alone,
so a re-run never undoes an abstract the coordinator added afterwards (the
``import_program_*`` scripts overwrite, which is why they need diffing first).

Each presenter is linked by their directory slug when they have an account,
so their own profile is what the page shows; otherwise they are named as an
outside speaker. The talks' times aren't known, so they have no sessions.

    manage.py import_scholarly_series_history [--dry-run]
"""

from __future__ import annotations

import datetime as dt

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

#: (date, slug, title, presenter's directory slug, presenter's name). Both of
#: Shanna's talks are one person: she gave the 2025 one as "Shanna Carlson".
TALKS = (
    (dt.date(2024, 2, 3), "femininity-and-the-spirit-of-decision",
     "Femininity and the Spirit of Decision",
     "shanna-carlson-de-la-torre", "Shanna Carlson de la Torre"),
    (dt.date(2024, 6, 8), "demanding-the-real-of-sexual-difference",
     "Demanding the Real of Sexual Difference: On Recent Lacanian Transphobia "
     "and Beyond", "matt-lovett", "Matt Lovett"),
    (dt.date(2024, 9, 21), "the-object-of-the-fundamental-fantasy",
     "Working through and from the object of the fundamental fantasy in the "
     "after-words of the clinic of addiction",
     "christopher-meyer", "Christopher Meyer"),
    (dt.date(2024, 10, 5), "after-words-a-poetics-and-logic-of-the-unconscious",
     "After Words: A poetics and logic of the unconscious in a novel",
     "annie-g-rogers-phd", "Annie Rogers"),
    (dt.date(2025, 2, 22), "treatment-for-the-unhoused-subject",
     "Dwelling on the Direction of the Treatment for the Unhoused Subject",
     "chris-vanderwees", "Chris Vanderwees"),
    (dt.date(2025, 5, 31), "georges-bataille-extends-a-sprig-of-life",
     "Georges Bataille Extends a Sprig of Life: Language, Experience, and the "
     "Out-of-Language", "shanna-carlson-de-la-torre", "Shanna Carlson"),
    (dt.date(2026, 3, 7), "the-perpetual-writing-of-the-dream",
     "The Perpetual Writing of the Dream", "diana-cuello", "Diana Cuello"),
)


def _members_by_directory_slug() -> dict:
    from accounts.models import User

    return {
        u.profile.directory_slug: u
        for u in User.objects.filter(is_active=True).select_related("profile")
    }


class Command(BaseCommand):
    help = "Make the Scholarly Seminar Series' pre-site talks events. Idempotent."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would be created; write nothing.",
        )

    def handle(self, *args, dry_run: bool, **opts):
        from events.models import Event, Speaker

        members = _members_by_directory_slug()
        created = 0
        for date, slug, title, directory_slug, name in TALKS:
            member = members.get(directory_slug)
            who = (f"member {member.get_full_name()}" if member
                   else f"outside speaker {name}")
            if Event.objects.filter(slug=slug).exists():
                self.stdout.write(f"  exists, left alone: {slug}")
                continue
            if dry_run:
                self.stdout.write(f"  would create: {slug} ({date}, {who})")
                continue
            with transaction.atomic():
                event = Event.objects.create(
                    title=title, slug=slug,
                    event_type=Event.Type.SCHOLARLY_SEMINAR,
                    start_date=date, end_date=date,
                    format=Event.Format.ONLINE,
                    online_venue=Event.OnlineVenue.EXTERNAL,  # they met on Zoom
                    status=Event.Status.CLOSED,
                    published=True,
                )
                event.ensure_workgroup()  # the Program Committee's, as for any talk
                if member:
                    event.member_speakers.add(member)
                else:
                    speaker, _ = Speaker.objects.get_or_create(
                        slug=slugify(name), defaults={"name": name},
                    )
                    event.speakers.add(speaker)
            created += 1
            self.stdout.write(f"  created: {slug} ({date}, {who})")
        self.stdout.write(self.style.SUCCESS(
            "Dry run: nothing written." if dry_run
            else f"Created {created} of {len(TALKS)} talks."
        ))
