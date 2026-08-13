"""``timezone.now().date()`` is the UTC date — this codebase wants the local one.

Django sets the process timezone to ``settings.TIME_ZONE``, so every plain
``DateField`` here (period boundaries, ``end_date``, ``due_date``) is a date in
the school's own timezone, while ``timezone.now()`` stays UTC-aware. From 17:00
Pacific the two disagree by a day, which is how an event ending today dropped
off ``/events/`` seven hours early (task #571).

The behavioural tests below pin the boundary by freezing the clock at
00:30 UTC — 17:30 the previous day in Los Angeles. The structural test is the
guard: this class of bug only fails CI for the few hours a day the runner
happens to be past midnight UTC, so nothing reliably catches the next one.
"""

from __future__ import annotations

import datetime as dt
import re
import subprocess
from decimal import Decimal
from pathlib import Path
from unittest import mock

import pytest
from django.utils import timezone

from accounts.models import Profile, User
from events.models import Event
from payments.models import DuesPeriod, Payment

pytestmark = pytest.mark.django_db

#: 2026-08-13 00:30 UTC is 2026-08-12 17:30 in America/Los_Angeles — inside the
#: seven-hour window each evening where the UTC date is already tomorrow.
EVENING = dt.datetime(2026, 8, 13, 0, 30, tzinfo=dt.timezone.utc)
LOCAL_DAY = dt.date(2026, 8, 12)
UTC_DAY = dt.date(2026, 8, 13)


def _freeze():
    return mock.patch("django.utils.timezone.now", return_value=EVENING)


def test_the_window_this_guards_is_real():
    """Guards the guard: if these two ever agree, the tests below prove nothing."""
    with _freeze():
        assert timezone.now().date() == UTC_DAY
        assert timezone.localdate() == LOCAL_DAY


# ---- Behaviour at the boundary ----------------------------------------

def _dues_period(*, start, end, slug="tz-guard"):
    """Note the explicit slug — a migration already seeds the real academic
    years, so a natural ``ay-2025-2026`` collides."""
    return DuesPeriod.objects.create(
        name=f"AY {start.year}", slug=slug,
        start_date=start, due_date=start, end_date=end,
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"),
        dues_amount_analyst=Decimal("150"),
    )


def test_an_event_ending_today_is_still_coming_up():
    """The landing page's "Coming up" list, the same shape as the /events/ bug."""
    from django.contrib.auth.models import AnonymousUser

    from events.upcoming import landing_events

    event = Event.objects.create(
        title="Ends tonight", slug="ends-tonight",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=LOCAL_DAY, end_date=LOCAL_DAY,
        published=True, visibility=Event.Visibility.PUBLIC,
    )
    with _freeze():
        assert event in landing_events(AnonymousUser())


def test_a_period_starting_tomorrow_is_still_refused():
    """``sync_dues_charges`` refuses a future period so next year's members
    don't show as owing early — on the UTC date, tomorrow already qualifies."""
    from payments.charges import sync_dues_charges

    user = User.objects.create_user(email="owes@example.com", password="x")
    user.profile.role = Profile.Role.ANALYST
    user.profile.standing = Profile.Standing.ACTIVE
    user.profile.save()
    period = _dues_period(
        start=LOCAL_DAY + dt.timedelta(days=1),
        end=LOCAL_DAY + dt.timedelta(days=365),
    )
    with _freeze():
        assert sync_dues_charges(period) == 0


def test_the_current_period_is_the_one_containing_today():
    """The period ends *today*, so on the UTC date it has already closed."""
    DuesPeriod.objects.all().delete()      # migrations seed the real years
    period = _dues_period(start=dt.date(2025, 9, 1), end=LOCAL_DAY)
    with _freeze():
        assert DuesPeriod.current() == period


def test_an_audit_note_is_stamped_with_the_local_date():
    """These lines are read by the treasurer as "when did this happen" — a note
    added at 5:30pm must not be dated tomorrow."""
    payment = Payment.objects.create(
        amount=Decimal("100.00"), payment_type=Payment.Type.DUES,
    )
    with _freeze():
        payment.add_note("Recorded offline.")
    assert payment.notes.startswith(f"[{LOCAL_DAY}]")


# ---- The guard --------------------------------------------------------

#: Migrations are historical and already applied — editing one changes nothing
#: that has run, so they keep whatever they were written with.
_ALLOWED = re.compile(r"/migrations/")


def test_no_production_or_test_code_uses_the_utc_date():
    """``timezone.localdate()`` is the one to use. This test exists because CI
    only catches the difference between 00:00 UTC and 17:00 Pacific."""
    root = Path(__file__).resolve().parent.parent
    # ``git grep`` rather than a walk: it stays on this branch's tracked files,
    # so sibling .claude-worktrees checkouts under the repo root aren't swept.
    # The pattern is alias-agnostic (``djtz.now().date()`` is how one slipped
    # past the first sweep), hence matching the call rather than the module.
    out = subprocess.run(
        ["git", "grep", "-n", r"now()\.date()", "--", "*.py"],
        cwd=root, capture_output=True, text=True,
    ).stdout
    offenders = [
        line for line in out.splitlines()
        if line.strip() and not _ALLOWED.search(line.split(":")[0])
        and not line.split(":")[0].endswith(Path(__file__).name)
    ]
    assert not offenders, (
        "Use timezone.localdate() — the date off timezone.now() is UTC.\n"
        "This matches prose as well as code, so spell it out in words rather "
        "than weakening the pattern:\n" + "\n".join(offenders)
    )
