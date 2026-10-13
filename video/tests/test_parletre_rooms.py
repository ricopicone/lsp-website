"""Personal meeting rooms on Parlêtre's index (task #751): your own always, and
someone else's only while it is in session and you hold an invitation."""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from video import services_personal as personal
from video.models import RoomInvitation

from .factories import daily_on
from .test_personal_rooms import member, non_member, room_for

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _daily_on():
    with daily_on:
        yield


@pytest.fixture
def live(monkeypatch):
    """The set of Daily room names with someone in them."""
    rooms: dict[str, list] = {}
    monkeypatch.setattr("video.services.presence_map", lambda: rooms)

    def _occupy(room, name="Ada Lovelace"):
        rooms[room.video_room.name] = [{"userName": name}]

    return _occupy


def invite(room, user, **kwargs):
    kwargs.setdefault("expires_at", personal.new_expiry())
    return RoomInvitation.objects.create(personal_room=room, invited_user=user, **kwargs)


def test_own_room_is_listed_before_it_exists(live):
    rooms = personal.parletre_rooms(member())
    assert rooms["own"] == {"room": None, "is_live": False, "people": []}


def test_own_room_shows_live_with_who_is_in_it(live):
    u = member()
    room = room_for(u)
    live(room, "Ada Lovelace")
    own = personal.parletre_rooms(u)["own"]
    assert own["is_live"] and own["people"] == ["Ada Lovelace"]


def test_non_member_has_no_own_room(live):
    assert personal.parletre_rooms(non_member())["own"] is None


def test_invited_room_listed_only_while_in_session(live):
    owner = member("owner@example.com", first="Grace", last="Hopper")
    guest = member("guest@example.com")
    room = room_for(owner)
    invite(room, guest)

    assert personal.parletre_rooms(guest)["in_progress"] == []
    live(room, "Grace Hopper")
    [entry] = personal.parletre_rooms(guest)["in_progress"]
    assert entry["room"] == room and entry["owner_name"] == "Grace Hopper"


def test_uninvited_or_lapsed_invitation_is_not_listed(live):
    owner = member("owner@example.com")
    room = room_for(owner)
    live(room)
    stranger = member("stranger@example.com")
    lapsed = member("lapsed@example.com")
    invite(room, lapsed, expires_at=timezone.now() - timedelta(days=1))
    revoked = member("revoked@example.com")
    invite(room, revoked, revoked_at=timezone.now())

    for u in (stranger, lapsed, revoked):
        assert personal.parletre_rooms(u)["in_progress"] == []


@override_settings(DAILY_ENABLED=False)
def test_nothing_listed_when_video_is_off():
    assert personal.parletre_rooms(member()) == {"own": None, "in_progress": []}


def test_parletre_index_renders_both(client, live):
    owner = member("owner@example.com", first="Grace", last="Hopper")
    guest = member("guest@example.com")
    room = room_for(owner)
    invite(room, guest)
    live(room, "Grace Hopper")
    client.force_login(guest)

    html = client.get(reverse("parletre:index")).content.decode()
    assert "My meeting room" in html
    assert reverse("video:my_room") in html
    assert "Grace Hopper's meeting room" in html
    assert reverse("video:personal_room", args=[room.slug]) in html
