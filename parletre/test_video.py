"""Parlêtre video channel kind — standalone board rooms."""
from __future__ import annotations

import pytest
from django.test import override_settings
from django.urls import reverse

from accounts.models import Profile, User
from parletre.models import Channel

pytestmark = pytest.mark.django_db

daily_on = override_settings(
    DAILY_ENABLED=True, DAILY_API_KEY="k", DAILY_DOMAIN="lsp.daily.co"
)


@pytest.fixture(autouse=True)
def _mock_daily(monkeypatch):
    from django.core.cache import cache

    cache.clear()
    monkeypatch.setattr(
        "video.daily.create_room",
        lambda name, properties=None: {"name": name, "url": f"https://lsp.daily.co/{name}"},
    )
    monkeypatch.setattr("video.daily.create_meeting_token", lambda **kw: "tok-1")
    yield
    cache.clear()


def _member(email="m@x.test", role=Profile.Role.ANALYST):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = role
    u.profile.save()
    return u


def _video_channel():
    return Channel.objects.create(
        name="All-member room", slug="all-member", kind=Channel.Kind.VIDEO,
        access=Channel.Access.OPEN,
    )


@daily_on
def test_member_sees_embedded_room(client):
    ch = _video_channel()
    client.force_login(_member())
    resp = client.get(reverse("parletre:channel", args=[ch.slug]))
    assert resp.status_code == 200
    assert b"room-token" in resp.content
    assert b"not recorded" in resp.content


@daily_on
def test_non_member_cannot_see_channel(client):
    ch = _video_channel()
    outsider = _member("o@x.test", role=Profile.Role.EXTERNAL)
    client.force_login(outsider)
    # Not visible to a non-member -> 404 from _visible_channel_or_404.
    assert client.get(reverse("parletre:channel", args=[ch.slug])).status_code == 404


@daily_on
def test_post_to_video_channel_is_404(client):
    ch = _video_channel()
    client.force_login(_member())
    resp = client.post(reverse("parletre:channel", args=[ch.slug]), {"body": "hi"})
    assert resp.status_code == 404


@daily_on
def test_index_shows_who_is_in_the_room(client, monkeypatch):
    _video_channel()
    monkeypatch.setattr(
        "video.daily.get_presence",
        lambda: {"lsp-ch-all-member": [{"userName": "Rico Picone"}]},
    )
    client.force_login(_member())
    resp = client.get(reverse("parletre:index"))
    assert resp.status_code == 200
    assert b"In the room: Rico Picone" in resp.content
    assert b"animate-breathe" in resp.content  # breathing Live badge


def test_disabled_shows_unavailable(client):
    ch = _video_channel()
    client.force_login(_member())
    resp = client.get(reverse("parletre:channel", args=[ch.slug]))
    assert resp.status_code == 200
    assert b"isn" in resp.content.lower()  # "isn't available"
