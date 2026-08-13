"""``manage.py resync_workgroup_names`` — repair names that drifted before the
sync existed (task #568)."""

from __future__ import annotations

from datetime import date
from io import StringIO

import pytest
from django.core.management import call_command

from events.models import Event
from parletre.models import Channel
from workgroups.models import Workgroup

pytestmark = pytest.mark.django_db


def _drifted():
    """A seminar whose workgroup + channels still hold the pre-edit title —
    the state prod was left in by the missing sync."""
    event = Event.objects.create(
        title="Beyond Principle; or Put A Socket In It", slug="beyond",
        event_type=Event.Type.SEMINAR,
        start_date=date(2026, 9, 1), end_date=date(2027, 5, 1),
    )
    wg = event.ensure_workgroup()
    Event.objects.filter(pk=event.pk).update(
        title="Beyond Principle; or, Put A Socket In It"
    )   # .update() fires no signals — exactly how the drift arose
    event.refresh_from_db()
    return event, wg


def test_dry_run_reports_drift_without_writing():
    event, wg = _drifted()
    out = StringIO()

    call_command("resync_workgroup_names", "--dry-run", stdout=out)

    wg.refresh_from_db()
    assert wg.name == "Beyond Principle; or Put A Socket In It"
    assert "beyond" in out.getvalue()


def test_it_renames_the_workgroup_and_its_channels():
    event, wg = _drifted()

    call_command("resync_workgroup_names", stdout=StringIO())

    wg.refresh_from_db()
    assert wg.name == "Beyond Principle; or, Put A Socket In It"
    assert wg.channels.get(kind=Channel.Kind.CHAT).name == (
        "Beyond Principle; or, Put A Socket In It chat"
    )
    assert wg.channels.get(kind=Channel.Kind.FORUM).description == (
        "Discussion for Beyond Principle; or, Put A Socket In It."
    )


def test_it_is_idempotent():
    _drifted()
    call_command("resync_workgroup_names", stdout=StringIO())
    out = StringIO()

    call_command("resync_workgroup_names", stdout=out)

    assert "0 renamed" in out.getvalue()


def test_it_leaves_a_committee_workgroup_alone():
    wg = Workgroup.objects.create(
        kind=Workgroup.Kind.COMMITTEE, name="Program Committee"
    )

    call_command("resync_workgroup_names", stdout=StringIO())

    wg.refresh_from_db()
    assert wg.name == "Program Committee"
