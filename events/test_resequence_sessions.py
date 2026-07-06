"""Session.sequence stays in chronological sync (signals + helper)."""

from __future__ import annotations

from datetime import date
from io import StringIO

import pytest
from django.core.management import call_command

from events.models import Event, Session


def _event():
    return Event.objects.create(
        title="Topology", slug="topology",
        start_date=date(2026, 9, 1), end_date=date(2027, 5, 31),
    )


def _session(event, iso_date):
    return Session.objects.create(
        event=event,
        start_at=f"{iso_date}T09:00:00Z",
        end_at=f"{iso_date}T11:00:00Z",
    )


@pytest.mark.django_db
def test_inserting_out_of_order_renumbers_by_date():
    event = _event()
    sep = _session(event, "2026-09-12")
    nov = _session(event, "2026-11-14")
    # The bug repro: a session added after November but dated October.
    oct_ = _session(event, "2026-10-10")

    for s in (sep, nov, oct_):
        s.refresh_from_db()
    assert sep.sequence == 1
    assert oct_.sequence == 2  # not "#3 by insertion order"
    assert nov.sequence == 3


@pytest.mark.django_db
def test_deleting_a_session_closes_the_gap():
    event = _event()
    s1 = _session(event, "2026-09-12")
    s2 = _session(event, "2026-10-10")
    s3 = _session(event, "2026-11-14")

    s2.delete()
    s1.refresh_from_db()
    s3.refresh_from_db()
    assert s1.sequence == 1
    assert s3.sequence == 2


@pytest.mark.django_db
def test_management_command_backfills():
    event = _event()
    # Simulate pre-signals drift via bulk_update (no signals fire).
    a = _session(event, "2026-09-12")
    b = _session(event, "2026-10-10")
    Session.objects.filter(pk=a.pk).update(sequence=1)
    Session.objects.filter(pk=b.pk).update(sequence=9)

    out = StringIO()
    call_command("resequence_sessions", "--slug", "topology", stdout=out)
    b.refresh_from_db()
    assert b.sequence == 2
    assert "#9 → #2" in out.getvalue()
