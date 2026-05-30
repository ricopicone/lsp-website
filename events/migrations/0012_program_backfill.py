"""Backfill Program rows + link annual-program-type Events.

For every distinct academic year currently represented by annual-program-
type Events (seminar, reading_group, cartel), create a Program row with
published=True (since those events were already public under the old
Event.published gate). Then link each event to its Program.
"""

import datetime

from django.db import migrations


ACADEMIC_YEAR_START_MONTH = 9
ANNUAL_PROGRAM_TYPES = ("seminar", "reading_group", "cartel")


def _academic_year_of(d: datetime.date) -> str:
    if d.month >= ACADEMIC_YEAR_START_MONTH:
        return f"{d.year}-{d.year + 1}"
    return f"{d.year - 1}-{d.year}"


def backfill_programs(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    Program = apps.get_model("events", "Program")

    annual_events = Event.objects.filter(event_type__in=ANNUAL_PROGRAM_TYPES)
    # Group by computed academic year.
    by_year: dict[str, list] = {}
    for ev in annual_events:
        by_year.setdefault(_academic_year_of(ev.start_date), []).append(ev)

    for ay, events in by_year.items():
        program, created = Program.objects.update_or_create(
            academic_year=ay,
            defaults={
                "name": f"Program {ay}",
                # If any of the events were published, mark the program
                # published so visibility is preserved.
                "published": any(ev.published for ev in events),
            },
        )
        for ev in events:
            ev.program_id = program.id
            ev.save(update_fields=("program",))


def unbackfill(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    Program = apps.get_model("events", "Program")
    Event.objects.filter(event_type__in=ANNUAL_PROGRAM_TYPES).update(program=None)
    Program.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("events", "0011_program_model")]
    operations = [migrations.RunPython(backfill_programs, unbackfill)]
