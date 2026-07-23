"""Manual seminar-access suspension (task #450 phase D, task 3).

A treasurer can flip ``Profile.seminar_access_suspended`` from the member
account page — a human, audited action; nothing automatic ever sets it
(do-not-over-automate). While set, the member's *registrant-derived*
membership in seminar/reading-group Workgroups (and the workgroup-gated
Parlêtre channel access that follows from it) is excluded; faculty status
is untouched.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import Profile, User
from events.models import Audience, Event, PriceTier
from registrations.models import Registration

pytestmark = pytest.mark.django_db


def _user(email, is_faculty=False):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.is_faculty = is_faculty
    u.profile.save()
    return u


def _seminar(slug="sem-suspend"):
    return Event.objects.create(
        title="Seminar on the Letter", slug=slug,
        event_type=Event.Type.SEMINAR,
        start_date=date(2026, 9, 1), end_date=date(2027, 5, 1),
    )


def _register(user, event, status=Registration.Status.PAID):
    tier = event.price_tiers.first() or PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("0.00")
    )
    return Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("0.00"), status=status,
    )


@pytest.fixture
def treasurer(client):
    u = User.objects.create_user(email="tr-susp@x.test", password="x", is_staff=True)
    client.force_login(u)
    return u


# ---------------------------------------------------------------- roster --

def test_suspended_registrant_excluded_from_workgroup_roster_faculty_stay():
    event = _seminar()
    wg = event.ensure_workgroup()

    teacher = _user("teacher-susp@x.test", is_faculty=True)
    event.add_faculty(teacher)
    paid = _user("paid-susp@x.test")
    _register(paid, event, status=Registration.Status.PAID)

    # Before suspension: both on the roster.
    assert wg.is_member(paid) is True
    assert {p.user for p in wg.participants()} == {teacher, paid}

    paid.profile.seminar_access_suspended = True
    paid.profile.save(update_fields=["seminar_access_suspended"])

    assert wg.is_member(paid) is False
    roster = {p.user for p in wg.participants()}
    assert paid not in roster
    assert teacher in roster  # faculty untouched


def test_suspended_registrant_loses_workgroup_channel_access():
    """Workgroup-gated Parlêtre channel access follows the roster derivation
    (``Workgroup.is_member`` / ``has_archive_access``)."""
    from parletre.permissions import channel_visible

    event = _seminar(slug="sem-suspend-channel")
    wg = event.ensure_workgroup()
    channel = wg.channels.first()
    assert channel is not None

    paid = _user("paid-chan-susp@x.test")
    _register(paid, event, status=Registration.Status.PAID)
    assert channel_visible(channel, paid) is True

    paid.profile.seminar_access_suspended = True
    paid.profile.save(update_fields=["seminar_access_suspended"])

    assert channel_visible(channel, paid) is False


def test_restore_reverses_the_exclusion():
    event = _seminar(slug="sem-suspend-restore")
    wg = event.ensure_workgroup()
    paid = _user("paid-restore@x.test")
    _register(paid, event, status=Registration.Status.PAID)

    paid.profile.seminar_access_suspended = True
    paid.profile.save(update_fields=["seminar_access_suspended"])
    assert wg.is_member(paid) is False

    paid.profile.seminar_access_suspended = False
    paid.profile.save(update_fields=["seminar_access_suspended"])
    assert wg.is_member(paid) is True


# --------------------------------------------------------------- toggle --

def test_treasurer_suspend_toggle_flips_flag_and_audits(client, treasurer):
    member = _user("target-susp@x.test")
    resp = client.post(
        reverse("treasurer_suspend_access", args=[member.id]),
        {"action": "suspend", "reason": "Balance six weeks past due."},
    )
    assert resp.status_code == 302
    member.profile.refresh_from_db()
    assert member.profile.seminar_access_suspended is True
    assert f"Suspended by treasurer {treasurer.email}" in member.profile.notes
    assert "Balance six weeks past due." in member.profile.notes


def test_treasurer_restore_toggle_flips_flag_and_audits(client, treasurer):
    member = _user("target-restore@x.test")
    member.profile.seminar_access_suspended = True
    member.profile.save(update_fields=["seminar_access_suspended"])

    resp = client.post(
        reverse("treasurer_suspend_access", args=[member.id]),
        {"action": "restore", "reason": "Balance settled in full."},
    )
    assert resp.status_code == 302
    member.profile.refresh_from_db()
    assert member.profile.seminar_access_suspended is False
    assert f"Restored by treasurer {treasurer.email}" in member.profile.notes
    assert "Balance settled in full." in member.profile.notes


def test_suspend_requires_a_reason(client, treasurer):
    member = _user("target-noreason@x.test")
    resp = client.post(
        reverse("treasurer_suspend_access", args=[member.id]),
        {"action": "suspend", "reason": "  "},
    )
    assert resp.status_code == 302
    member.profile.refresh_from_db()
    assert member.profile.seminar_access_suspended is False


def test_suspend_toggle_non_treasurer_404s(client):
    member = _user("target-nontreas@x.test")
    other = _user("nontreasurer@x.test")
    client.force_login(other)
    resp = client.post(
        reverse("treasurer_suspend_access", args=[member.id]),
        {"action": "suspend", "reason": "Trying to sneak in."},
    )
    assert resp.status_code == 404
    member.profile.refresh_from_db()
    assert member.profile.seminar_access_suspended is False


def test_suspend_toggle_anonymous_redirects(client):
    member = _user("target-anon@x.test")
    resp = client.post(
        reverse("treasurer_suspend_access", args=[member.id]),
        {"action": "suspend", "reason": "Trying to sneak in."},
    )
    assert resp.status_code == 302
    assert "/accounts/login" in resp["Location"]


def test_member_detail_page_shows_suspension_badge_and_toggle(client, treasurer):
    member = _user("target-badge@x.test")
    resp = client.get(reverse("treasurer_member_detail", args=[member.id]))
    assert resp.status_code == 200
    assert b"Suspend seminar group access" in resp.content

    member.profile.seminar_access_suspended = True
    member.profile.save(update_fields=["seminar_access_suspended"])
    resp = client.get(reverse("treasurer_member_detail", args=[member.id]))
    assert b"Seminar group access suspended" in resp.content
    assert b"Restore access" in resp.content
