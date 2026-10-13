"""Window openings ride the five-minute send_meeting_reminders timer (task #813)."""

import pytest
from django.core.management import call_command

from elections.tests.factories import make_election, make_member

pytestmark = pytest.mark.django_db


def test_meeting_reminders_advances_elections(django_capture_on_commit_callbacks, mailoutbox):
    voter = make_member()
    e = make_election("nominating")
    with django_capture_on_commit_callbacks(execute=True):
        call_command("send_meeting_reminders")
    e.refresh_from_db()
    assert e.call_sent_at
    assert voter.email in {m.to[0] for m in mailoutbox}


def test_dry_run_sends_nothing():
    e = make_election("nominating")
    call_command("send_meeting_reminders", "--dry-run")
    e.refresh_from_db()
    assert e.call_sent_at is None


def test_election_failure_does_not_stop_reminders(monkeypatch):
    from elections import services

    def boom(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(services, "advance_elections", boom)
    call_command("send_meeting_reminders")  # must not raise
