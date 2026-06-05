"""Parlêtre-wide 'who's online' — global heartbeat + per-chat presence."""
from __future__ import annotations

import pytest
from django.core.cache import cache
from django.urls import reverse

from accounts.models import Profile, User
from parletre import presence
from parletre.models import Channel

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _member(email="m@x.test", name="Mem Ber"):
    first, last = name.split(" ", 1)
    u = User.objects.create_user(email=email, password="x", first_name=first, last_name=last)
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    return u


def _backdate(key, user_id):
    store = cache.get(key)
    store[user_id]["ts"] -= presence.HEARTBEAT_TTL + 10
    cache.set(key, store, 900)


# --- global ---

def test_global_touch_and_prune():
    u = _member("a@x.test", "Alice A")
    assert presence.online_global() == []
    presence.touch_global(u)
    assert [p["name"] for p in presence.online_global()] == ["Alice A"]
    _backdate(presence._GLOBAL_KEY, u.id)
    assert presence.online_global() == []  # stale entry pruned


# --- per-channel (connection-counted) ---

def test_channel_handles_multiple_tabs():
    u = _member("c@x.test", "Cara C")
    cid = 99
    presence.join_channel(cid, u)
    presence.join_channel(cid, u)  # a second tab
    assert presence.online_channel(cid) == ["Cara C"]
    presence.leave_channel(cid, u)  # close one tab — still here
    assert presence.online_channel(cid) == ["Cara C"]
    presence.leave_channel(cid, u)  # close the last
    assert presence.online_channel(cid) == []


def test_channel_prunes_stale_after_unclean_disconnect():
    u = _member("d@x.test", "Dee D")
    cid = 7
    presence.join_channel(cid, u)
    _backdate(presence._chan(cid), u.id)
    assert presence.online_channel(cid) == []


# --- heartbeat endpoint ---

def test_heartbeat_requires_login(client):
    assert client.post(reverse("parletre:heartbeat")).status_code in (302, 403)


def test_heartbeat_marks_online_and_returns_roster(client):
    me = _member("me@x.test", "Me Myself")
    other = _member("o@x.test", "Otto O")
    presence.touch_global(other)
    client.force_login(me)
    resp = client.post(reverse("parletre:heartbeat"))
    assert resp.status_code == 200
    names = [p["name"] for p in resp.json()["online"]]
    assert "Me Myself" in names and "Otto O" in names


# --- index surfaces ---

def test_index_shows_online_now_and_chat_presence(client):
    me = _member("i@x.test", "Ima Online")
    ch = Channel.objects.create(
        name="Lounge", slug="lounge-x", kind=Channel.Kind.CHAT, access=Channel.Access.OPEN
    )
    presence.touch_global(me)              # someone is online site-wide
    presence.join_channel(ch.id, me)       # and present in a chat channel
    client.force_login(me)
    body = client.get(reverse("parletre:index")).content.decode()
    assert "Online now" in body
    assert "Ima Online" in body
    assert "1 here: Ima Online" in body    # per-channel "who's here" on the board
