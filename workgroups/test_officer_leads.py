"""Task #480 — the school officers lead the Board and the Meeting of Analysts.

The President / Vice-President hold no ``WorkgroupMembership`` on the Meeting of
Analysts: its leadership is derived from ``StaffRole`` holders synced off the
Board roster (task #428). These tests pin the predicate that teaches the
permission layer about that derivation, and pin its deliberate narrowness.
"""

from __future__ import annotations

import datetime

import pytest

from accounts.models import Profile, User
from committees.models import Committee
from core.models import StaffRole
from workgroups.models import Workgroup, WorkgroupMembership
from workgroups.permissions import is_workgroup_lead, officer_lead_titles

pytestmark = pytest.mark.django_db


def _user(email, role=Profile.Role.ANALYST):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = role
    u.profile.save()
    return u


def _president(email="pres@x.test"):
    u = _user(email)
    StaffRole.objects.get(key=StaffRole.PRESIDENT).holders.add(u)
    return u


def _vice_president(email="vp@x.test"):
    u = _user(email)
    StaffRole.objects.get(key=StaffRole.VICE_PRESIDENT).holders.add(u)
    return u


def _moa():
    return Committee.objects.get(slug="meeting-of-analysts").workgroup


def _board():
    return Committee.objects.get(slug="board").workgroup


def test_officer_leads_the_meeting_of_analysts():
    assert is_workgroup_lead(_president(), _moa()) is True
    assert is_workgroup_lead(_vice_president(), _moa()) is True


def test_officer_leads_the_board():
    assert is_workgroup_lead(_president(), _board()) is True


def test_officer_does_not_lead_other_groups():
    """The narrowness is the decision (spec decision 1), so it is pinned."""
    pres = _president()
    cartel = Workgroup.objects.create(kind=Workgroup.Kind.CARTEL, name="Cartel X")
    seminar = Workgroup.objects.create(kind=Workgroup.Kind.SEMINAR, name="Seminar X")
    pc = Committee.objects.get(slug="programming-committee").workgroup
    assert is_workgroup_lead(pres, cartel) is False
    assert is_workgroup_lead(pres, seminar) is False
    assert is_workgroup_lead(pres, pc) is False


def test_plain_analyst_does_not_lead_the_meeting():
    assert is_workgroup_lead(_user("plain@x.test"), _moa()) is False


def test_stored_lead_role_still_leads():
    cartel = Workgroup.objects.create(kind=Workgroup.Kind.CARTEL, name="Cartel Y")
    chair = _user("chair@x.test")
    WorkgroupMembership.objects.create(
        workgroup=cartel, user=chair, role=WorkgroupMembership.Role.CHAIR,
        start_date=datetime.date(2000, 1, 1),
    )
    assert is_workgroup_lead(chair, cartel) is True


def test_anonymous_never_leads():
    from django.contrib.auth.models import AnonymousUser
    assert is_workgroup_lead(AnonymousUser(), _moa()) is False


def test_officer_lead_titles_maps_users_to_titles():
    pres, vp = _president(), _vice_president()
    titles = officer_lead_titles(_moa())
    assert titles == {pres.pk: "President", vp.pk: "Vice President"}


def test_officer_lead_titles_empty_without_committee():
    cartel = Workgroup.objects.create(kind=Workgroup.Kind.CARTEL, name="Cartel Z")
    assert officer_lead_titles(cartel) == {}


# ---- Consequence: the Meeting of Analysts is a led group ----------------

def test_meeting_of_analysts_is_led_when_an_officer_serves():
    from workgroups.permissions import workgroup_has_leads
    _president()
    assert workgroup_has_leads(_moa()) is True


def test_meeting_decision_register_narrows_to_officers():
    """A led group's register is for its leads; a plain analyst no longer
    records the Meeting's decisions (spec decision 2)."""
    from workgroups.permissions import can_register_decision
    pres = _president()
    plain = _user("plain2@x.test")
    moa = _moa()
    assert can_register_decision(pres, moa) is True
    assert can_register_decision(plain, moa) is False


def test_cartel_stays_leaderless():
    """The regression guard for the scoping: no cartel becomes lead-led, so
    ordinary cartel members keep their decision register."""
    from workgroups.permissions import can_register_decision, workgroup_has_leads
    _president()
    cartel = Workgroup.objects.create(
        kind=Workgroup.Kind.CARTEL, name="Cartel W", has_decisions=True
    )
    member = _user("cm@x.test")
    WorkgroupMembership.objects.create(
        workgroup=cartel, user=member, start_date=datetime.date(2000, 1, 1)
    )
    assert workgroup_has_leads(cartel) is False
    assert can_register_decision(member, cartel) is True
