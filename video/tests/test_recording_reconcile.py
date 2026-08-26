"""Recovering recordings the Daily webhook never delivered (task #475).

The webhook is the only path that creates a Recording row, so when delivery
fails the recording exists on Daily and in our bucket while the site shows
nothing. These cover the sweep that repairs that, and — just as important —
the three things it must refuse to touch.
"""
from __future__ import annotations

import pytest
from django.core.management import call_command

from video import services
from video.models import DailyRoom, Recording

from .factories import daily_on, special_event

pytestmark = pytest.mark.django_db


def _daily_row(rec_id, *, room="lsp-event-special", status="finished", duration=30):
    return {
        "id": rec_id,
        "room_name": room,
        "start_ts": 1787678512,
        "status": status,
        "duration": duration,
        "s3key": f"lsp/{room}/{rec_id}",
    }


@pytest.fixture
def event_room():
    event = special_event()
    DailyRoom.objects.create(
        name="lsp-event-special", url="https://lsp.daily.co/lsp-event-special", event=event
    )
    return event


def _stub_list(monkeypatch, *pages):
    """Serve ``pages`` in order, so paging is exercised as Daily would drive it."""
    calls = []

    def _fake(*, limit=100, starting_after=None, room_name=None):
        calls.append(starting_after)
        idx = len(calls) - 1
        return {"data": list(pages[idx]) if idx < len(pages) else []}

    monkeypatch.setattr("video.daily.list_recordings", _fake)
    return calls


def test_missing_recording_is_ingested_unreleased(monkeypatch, event_room):
    _stub_list(monkeypatch, [_daily_row("rec-1")])

    created, updated, skipped = services.reconcile_recordings()

    assert (created, updated, skipped) == (1, 0, 0)
    rec = Recording.objects.get(daily_recording_id="rec-1")
    assert rec.status == Recording.Status.READY
    assert rec.event == event_room
    assert rec.duration_seconds == 30
    assert rec.s3_key == "lsp/lsp-event-special/rec-1"
    # A recovered recording is released to nobody until a host says otherwise —
    # the whole point is that recovery is not publication.
    assert rec.listing_visibility == Recording.Visibility.OWNERS
    assert rec.content_visibility == Recording.Visibility.OWNERS


def test_known_ready_recording_is_left_alone(monkeypatch, event_room):
    rec = Recording.objects.create(
        daily_recording_id="rec-1", status=Recording.Status.READY,
        listing_visibility=Recording.Visibility.MEMBERS,
        content_visibility=Recording.Visibility.MEMBERS,
    )
    _stub_list(monkeypatch, [_daily_row("rec-1")])

    assert services.reconcile_recordings() == (0, 0, 1)
    rec.refresh_from_db()
    # Re-ingesting would reset a visibility a host had deliberately widened.
    assert rec.listing_visibility == Recording.Visibility.MEMBERS


def test_stuck_recording_row_is_repaired(monkeypatch, event_room):
    """`recording.started` landed but ready-to-download never did."""
    Recording.objects.create(
        daily_recording_id="rec-1", status=Recording.Status.RECORDING
    )
    _stub_list(monkeypatch, [_daily_row("rec-1")])

    assert services.reconcile_recordings() == (0, 1, 0)
    rec = Recording.objects.get(daily_recording_id="rec-1")
    assert rec.status == Recording.Status.READY
    assert rec.s3_key == "lsp/lsp-event-special/rec-1"


def test_purged_recording_is_not_resurrected(monkeypatch, event_room):
    """A DELETED row whose Daily-side delete failed is still listed by Daily."""
    Recording.objects.create(
        daily_recording_id="rec-1", status=Recording.Status.DELETED, s3_key=""
    )
    _stub_list(monkeypatch, [_daily_row("rec-1")])

    assert services.reconcile_recordings() == (0, 0, 1)
    rec = Recording.objects.get(daily_recording_id="rec-1")
    assert rec.status == Recording.Status.DELETED
    assert rec.s3_key == ""


def test_unfinished_recording_is_left_to_the_webhook(monkeypatch, event_room):
    _stub_list(monkeypatch, [_daily_row("rec-1", status="in-progress")])

    assert services.reconcile_recordings() == (0, 0, 1)
    assert not Recording.objects.filter(daily_recording_id="rec-1").exists()


def test_pages_until_daily_runs_out(monkeypatch, event_room):
    full = [_daily_row(f"rec-{i}") for i in range(services.RECORDINGS_PAGE_SIZE)]
    calls = _stub_list(monkeypatch, full, [_daily_row("rec-last")])

    created, _, _ = services.reconcile_recordings()

    assert created == services.RECORDINGS_PAGE_SIZE + 1
    # Second page asked Daily to continue after the last id of the first.
    assert calls == [None, f"rec-{services.RECORDINGS_PAGE_SIZE - 1}"]


def test_dry_run_writes_nothing(monkeypatch, event_room):
    _stub_list(monkeypatch, [_daily_row("rec-1")])

    assert services.reconcile_recordings(dry_run=True) == (1, 0, 0)
    assert not Recording.objects.exists()


@daily_on
def test_command_reports_what_it_did(monkeypatch, event_room, capsys):
    _stub_list(monkeypatch, [_daily_row("rec-1")])

    call_command("reconcile_daily_recordings")

    assert "1 new recording" in capsys.readouterr().out
    assert Recording.objects.filter(daily_recording_id="rec-1").exists()


def test_command_is_inert_when_daily_is_off(monkeypatch, event_room, capsys):
    def _never(*a, **kw):  # pragma: no cover - asserts it is not reached
        raise AssertionError("reconcile must not call Daily when disabled")

    monkeypatch.setattr("video.daily.list_recordings", _never)
    call_command("reconcile_daily_recordings")
    assert "not enabled" in capsys.readouterr().out
