"""External-speaker invitation token (task #463)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.utils import timezone

from accounts.models import User
from events.models import Event, Speaker, SpeakerInvitation

pytestmark = pytest.mark.django_db


def _speaker_with_user(email="d@x.test"):
    u = User.objects.create_user(email=email)
    s = Speaker.objects.create(name="Derek Hook", slug="dh-inv", email=email, user=u)
    return s, u


def test_invitation_is_valid_until_expiry_and_use():
    s, u = _speaker_with_user()
    inv = SpeakerInvitation.objects.create(
        speaker=s, user=u, expires_at=timezone.now() + timedelta(days=10)
    )
    assert inv.token
    assert inv.is_valid is True
    inv.consume()
    assert inv.used_at is not None
    assert inv.is_valid is False


def test_invitation_expired_is_invalid():
    s, u = _speaker_with_user("e@x.test")
    inv = SpeakerInvitation.objects.create(
        speaker=s, user=u, expires_at=timezone.now() - timedelta(minutes=1)
    )
    assert inv.is_expired() is True
    assert inv.is_valid is False


def test_refresh_issues_new_token_and_clears_use():
    s, u = _speaker_with_user("f@x.test")
    inv = SpeakerInvitation.objects.create(
        speaker=s, user=u, expires_at=timezone.now() - timedelta(days=1)
    )
    old = inv.token
    inv.consume()
    inv.refresh()
    assert inv.token != old
    assert inv.used_at is None
    assert inv.is_valid is True
