"""Tests for the reversible #360 disable of school-wide social + private chats."""

import pytest
from django.test import override_settings
from django.urls import reverse

from accounts.models import Profile, User
from parletre.models import Channel
from parletre.permissions import channel_visible


def _member(email, role=Profile.Role.ANALYST, is_staff=False):
    u = User.objects.create_user(email=email, password="x", is_staff=is_staff)
    u.profile.role = role
    u.profile.save()
    return u


def _channel(slug, access=Channel.Access.OPEN, kind=Channel.Kind.CHAT, ttl=None):
    return Channel.objects.create(
        slug=slug, name=slug.title(), access=access, kind=kind,
        message_ttl_seconds=ttl,
    )


@pytest.mark.django_db
@override_settings(PARLETRE_SCHOOLWIDE_SOCIAL_ENABLED=False, PARLETRE_PRIVATE_CHATS_ENABLED=False)
def test_member_cannot_see_schoolwide_social_when_off():
    m = _member("m@x.test")
    assert channel_visible(_channel("lounge"), m) is False
    assert channel_visible(_channel("the-commons", kind=Channel.Kind.FORUM), m) is False
    assert channel_visible(_channel("purloined-letters", ttl=86400), m) is False
    # Kept-visible channels stay visible:
    assert channel_visible(_channel("announcements", kind=Channel.Kind.FORUM), m) is True


@pytest.mark.django_db
@override_settings(PARLETRE_SCHOOLWIDE_SOCIAL_ENABLED=False, PARLETRE_PRIVATE_CHATS_ENABLED=False)
def test_staff_still_sees_schoolwide_social_when_off():
    staff = _member("s@x.test", is_staff=True)
    assert channel_visible(_channel("lounge"), staff) is True


@pytest.mark.django_db
@override_settings(PARLETRE_SCHOOLWIDE_SOCIAL_ENABLED=False, PARLETRE_PRIVATE_CHATS_ENABLED=False)
def test_private_chat_hidden_even_from_creator_when_off():
    creator = _member("c@x.test")
    ch = _channel("dm-1", access=Channel.Access.PRIVATE)
    ch.members.add(creator)
    ch.moderators.add(creator)   # creators are moderators
    assert channel_visible(ch, creator) is False


@pytest.mark.django_db
@override_settings(PARLETRE_SCHOOLWIDE_SOCIAL_ENABLED=True, PARLETRE_PRIVATE_CHATS_ENABLED=True)
def test_flags_on_restores_visibility():
    m = _member("m2@x.test")
    assert channel_visible(_channel("lounge"), m) is True
    ch = _channel("dm-2", access=Channel.Access.PRIVATE)
    ch.members.add(m)
    assert channel_visible(ch, m) is True


@pytest.mark.django_db
@override_settings(PARLETRE_PRIVATE_CHATS_ENABLED=False)
def test_create_private_chat_blocked_when_off(client):
    m = _member("cc@x.test")
    client.force_login(m)
    resp = client.get(reverse("parletre:create_private_chat"), SERVER_NAME="localhost")
    assert resp.status_code == 403


@pytest.mark.django_db
@override_settings(PARLETRE_PRIVATE_CHATS_ENABLED=False)
def test_new_private_chat_button_hidden_when_off(client):
    m = _member("bb@x.test")
    client.force_login(m)
    body = client.get(reverse("parletre:index"), SERVER_NAME="localhost").content.decode()
    assert reverse("parletre:create_private_chat") not in body
