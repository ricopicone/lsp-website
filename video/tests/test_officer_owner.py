"""Task #480 — the school officers moderate and record the Meeting's room.

Before this, opening the Meeting of Analysts' video room gave *nobody*
moderator controls and *nobody* a Record button: its leaders are derived
StaffRole holders, and ``is_owner`` only saw stored memberships.
"""

from __future__ import annotations

import pytest

from accounts.models import Profile, User
from committees.models import Committee
from core.models import StaffRole
from video import services
from video.models import DailyRoom, Recording
from workgroups.models import Workgroup

pytestmark = pytest.mark.django_db


def _analyst(email):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    return u


def _president(email="pres@x.test"):
    u = _analyst(email)
    StaffRole.objects.get(key=StaffRole.PRESIDENT).holders.add(u)
    return u


def _moa():
    return Committee.objects.get(slug="meeting-of-analysts").workgroup


def test_president_is_owner_of_the_meetings_room():
    assert services.is_owner(_moa(), _president()) is True


def test_plain_analyst_is_not_owner_of_the_meetings_room():
    assert services.is_owner(_moa(), _analyst("plain@x.test")) is False


def test_president_is_not_owner_of_a_cartel_room():
    cartel = Workgroup.objects.create(kind=Workgroup.Kind.CARTEL, name="Cartel V")
    assert services.is_owner(cartel, _president()) is False


def test_president_hosts_a_recording_from_the_meetings_room():
    room = DailyRoom.objects.create(
        workgroup=_moa(), name="lsp-moa", url="https://lsp.daily.co/lsp-moa"
    )
    rec = Recording.objects.create(room=room, daily_recording_id="r1")
    assert rec._can_host(_president()) is True
    assert rec._can_host(_analyst("plain2@x.test")) is False
