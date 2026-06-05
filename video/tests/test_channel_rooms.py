from __future__ import annotations

import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.test import RequestFactory

from parletre.models import Channel
from video import services
from video.models import DailyRoom

from .factories import daily_on, seminar, user, video_channel

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _mock_daily(monkeypatch):
    monkeypatch.setattr(
        "video.daily.create_room",
        lambda name, properties=None: {"name": name, "url": f"https://lsp.daily.co/{name}"},
    )
    monkeypatch.setattr("video.daily.create_meeting_token", lambda **kw: "tok-xyz")


def _req(u):
    r = RequestFactory().get("/")
    r.user = u
    return r


@daily_on
def test_channel_owned_room_name_is_prefixed():
    ch = video_channel(slug="all-hands", access=Channel.Access.OPEN)
    room = services.ensure_room(ch)
    assert room.name == "lsp-ch-all-hands"
    assert room.channel_id == ch.pk and room.workgroup_id is None


@daily_on
def test_workgroup_access_channel_reuses_workgroup_room():
    wg = seminar().ensure_workgroup()
    # The workgroup auto-provisions a video channel (Discuss/Chat/Video).
    ch = wg.channels.get(kind=Channel.Kind.VIDEO)
    member = user("m@x.test")
    wg_room = services.ensure_room(wg)
    # The channel context resolves owner = channel.workgroup, so it returns the
    # *workgroup* room — no separate channel room is created.
    ctx = services.channel_room_context(_req_member(wg, member, ch), ch)
    assert ctx["room_url"] == wg_room.url
    assert not DailyRoom.objects.filter(channel=ch).exists()


def _req_member(wg, member, ch):
    # Give the member workgroup membership so channel_visible passes.
    from datetime import date

    from workgroups.models import WorkgroupMembership

    WorkgroupMembership.objects.create(
        workgroup=wg, user=member, role=WorkgroupMembership.Role.MEMBER,
        start_date=date(2026, 1, 1),
    )
    return _req(member)


@daily_on
def test_channel_room_context_denies_non_member():
    # An open channel is visible only to parletre members; an external user is not.
    from accounts.models import Profile

    ch = video_channel(access=Channel.Access.OPEN)
    outsider = user("o@x.test")
    outsider.profile.role = Profile.Role.EXTERNAL
    outsider.profile.save()
    with pytest.raises(PermissionDenied):
        services.channel_room_context(_req(outsider), ch)


@daily_on
def test_channel_room_context_member_gets_token():
    ch = video_channel(access=Channel.Access.OPEN)
    member = user("m2@x.test")
    ctx = services.channel_room_context(_req(member), ch)
    assert ctx["room_url"].endswith("lsp-ch-vid")
    assert ctx["room_token"] == "tok-xyz"


def test_channel_room_context_unavailable_when_disabled():
    # Daily off (default) -> graceful unavailable, not an error.
    ch = video_channel(access=Channel.Access.OPEN)
    member = user("m3@x.test")
    ctx = services.channel_room_context(_req(member), ch)
    assert ctx == {"room_unavailable": True}


def test_room_requires_exactly_one_owner():
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            DailyRoom.objects.create(name="orphan", url="https://x/y")


def test_room_rejects_two_owners():
    wg = seminar().ensure_workgroup()
    ch = video_channel()
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            DailyRoom.objects.create(name="both", url="https://x/y", workgroup=wg, channel=ch)
