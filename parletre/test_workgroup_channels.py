"""Stage 2 — Parlêtre × Workgroups integration.

Auto-provisioning of a workgroup's channel, and the WORKGROUP access rules:
membership gates entry; intimate kinds (cartel / working group) get no staff
bypass, while committee / seminar channels keep staff oversight.
"""

from __future__ import annotations

import datetime

import pytest

from accounts.models import Profile, User
from parletre.models import Channel
from parletre.permissions import channel_can_moderate, channel_visible
from workgroups.models import Workgroup, WorkgroupMembership

pytestmark = pytest.mark.django_db


def _user(email, role=Profile.Role.ANALYST, is_staff=False):
    u = User.objects.create_user(email=email, password="x", is_staff=is_staff)
    u.profile.role = role
    u.profile.save()
    return u


def _wg(kind=Workgroup.Kind.CARTEL, name="A Group", **kw):
    return Workgroup.objects.create(kind=kind, name=name, **kw)


def _join(wg, user, role=WorkgroupMembership.Role.MEMBER):
    return WorkgroupMembership.objects.create(
        workgroup=wg, user=user, role=role, start_date=datetime.date(2026, 1, 1)
    )


# ---- Auto-provisioning -------------------------------------------------

def test_workgroup_gets_a_channel_on_creation():
    wg = _wg(name="Speech and Writing")
    ch = wg.channels.first()
    assert ch is not None
    assert ch.access == Channel.Access.WORKGROUP
    assert ch.kind == Channel.Kind.FORUM
    assert ch.workgroup_id == wg.id


def test_no_channel_when_has_channel_false():
    wg = _wg(name="Quiet Group", has_channel=False)
    assert wg.channels.count() == 0


def test_provision_is_idempotent():
    wg = _wg(name="Once Only")
    wg.description = "edited"
    wg.save()
    assert wg.channels.count() == 1


def test_channel_category_matches_kind():
    cartel = _wg(kind=Workgroup.Kind.CARTEL, name="Cartel X")
    committee = _wg(kind=Workgroup.Kind.COMMITTEE, name="Board")
    assert cartel.channels.first().category.name == "Cartels"
    assert committee.channels.first().category.name == "Committees"


# ---- WORKGROUP access (visibility) ------------------------------------

def test_member_sees_channel_nonmember_does_not():
    wg = _wg()
    ch = wg.channels.first()
    insider = _user("in@x.test")
    outsider = _user("out@x.test")          # an LSP member, but not in the group
    _join(wg, insider)
    assert channel_visible(ch, insider) is True
    assert channel_visible(ch, outsider) is False


def test_cartel_channel_has_no_staff_bypass():
    wg = _wg(kind=Workgroup.Kind.CARTEL, name="Intimate Cartel")
    ch = wg.channels.first()
    staff = _user("staff@x.test", is_staff=True)
    assert channel_visible(ch, staff) is False
    assert channel_can_moderate(ch, staff) is False


def test_committee_channel_keeps_staff_bypass():
    wg = _wg(kind=Workgroup.Kind.COMMITTEE, name="Ethics Committee")
    ch = wg.channels.first()
    staff = _user("staff@x.test", is_staff=True)
    assert channel_visible(ch, staff) is True
    assert channel_can_moderate(ch, staff) is True


# ---- WORKGROUP moderation ---------------------------------------------

def test_plus_one_and_chair_moderate_plain_member_does_not():
    wg = _wg()
    ch = wg.channels.first()
    plus_one = _user("plusone@x.test")
    plain = _user("plain@x.test")
    _join(wg, plus_one, role=WorkgroupMembership.Role.PLUS_ONE)
    _join(wg, plain)
    assert channel_can_moderate(ch, plus_one) is True
    assert channel_can_moderate(ch, plain) is False


def test_workgroup_channel_post_gated_by_membership():
    from parletre.permissions import channel_can_post

    wg = _wg()
    ch = wg.channels.first()
    insider = _user("in@x.test")
    outsider = _user("out@x.test")
    _join(wg, insider)
    assert channel_can_post(ch, insider) is True
    assert channel_can_post(ch, outsider) is False
