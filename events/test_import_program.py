"""Tests for the 2026-2027 program import (task #245: structured fields).

The source descriptions arrived as one blob (prose + "Readings:" + a "---"
metadata tail); the command now writes the split fields. These tests pin that
no entry regresses to the monolithic form.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command

from events.management.commands.import_program_2026_2027 import SEMINARS
from events.models import Event

pytestmark = pytest.mark.django_db


def test_import_populates_structured_fields():
    call_command("import_program_2026_2027")
    assert Event.objects.filter(slug__endswith="-2026-27").count() == len(SEMINARS)
    for s in SEMINARS:
        e = Event.objects.get(slug=s["slug"])
        # The blob structure must not reappear in the prose description.
        assert "Readings:" not in e.description
        assert "\n---\n" not in e.description
        assert "Fee:" not in e.description
        assert "Dates and times:" not in e.description
        assert e.readings == "\n".join(s.get("readings") or [])
        assert e.schedule_note == s.get("schedule_note", "")
        assert e.contact == s.get("contact", "")
        assert e.fee_note == s.get("fee_note", "")


def test_import_sets_in_person_formats():
    call_command("import_program_2026_2027")
    assert (
        Event.objects.get(slug="sounding-out-the-signifier-2026-27").format
        == Event.Format.IN_PERSON
    )
    assert (
        Event.objects.get(slug="psychoanalysis-place-and-time-la-2026-27").format
        == Event.Format.IN_PERSON
    )
    assert (
        Event.objects.get(slug="das-unbehagen-2026-27").format
        == Event.Format.ONLINE
    )


def test_import_is_idempotent():
    call_command("import_program_2026_2027")
    call_command("import_program_2026_2027")
    assert Event.objects.filter(slug__endswith="-2026-27").count() == len(SEMINARS)
