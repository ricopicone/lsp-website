"""External-speaker invitation token (task #463)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, User
from committees.models import Committee
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


def _special_event(slug="inv-talk"):
    return Event.objects.create(
        title="Working with Masochism", slug=slug,
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2030, 9, 6), end_date=date(2030, 9, 6),
        published=True, status=Event.Status.OPEN,
    )


def test_provision_login_creates_external_user():
    from events.speaker_invitations import provision_login
    s = Speaker.objects.create(name="Derek Hook", slug="dh-prov", email="derek@x.test")
    u = provision_login(s)
    s.refresh_from_db()
    assert s.user == u
    assert u.email == "derek@x.test"
    assert u.profile.role == Profile.Role.EXTERNAL
    assert u.profile.public is False
    assert u.has_usable_password() is False
    assert u.first_name == "Derek" and u.last_name == "Hook"


def test_provision_login_links_existing_user_not_duplicate():
    from events.speaker_invitations import provision_login
    existing = User.objects.create_user(email="dup@x.test", first_name="Dup")
    s = Speaker.objects.create(name="Dup Person", slug="dup-p", email="dup@x.test")
    u = provision_login(s)
    assert u == existing
    assert User.objects.filter(email="dup@x.test").count() == 1


def test_send_invitation_creates_token_and_sends_one_email():
    from events.speaker_invitations import send_invitation
    e = _special_event()
    s = Speaker.objects.create(name="Derek Hook", slug="dh-send", email="derek@x.test")
    e.speakers.add(s)
    inv = send_invitation(s, e, message="Looking forward to it.")
    assert inv.is_valid
    assert inv.user.email == "derek@x.test"
    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    assert inv.token in body
    assert "Looking forward to it." in body
    assert mail.outbox[0].to == ["derek@x.test"]


def test_send_invitation_resend_refreshes_token():
    from events.speaker_invitations import send_invitation
    e = _special_event("inv-talk-2")
    s = Speaker.objects.create(name="Derek Hook", slug="dh-resend", email="derek@x.test")
    e.speakers.add(s)
    inv1 = send_invitation(s, e, message="first")
    t1 = inv1.token
    inv2 = send_invitation(s, e, message="second")
    assert inv2.pk == inv1.pk
    assert inv2.token != t1
    assert len(mail.outbox) == 2


def _pc_user():
    u = User.objects.create_user(email="pc@x.test")
    Committee.objects.get_or_create(
        slug="programming-committee", defaults={"name": "Programming Committee"}
    )[0].add_member(u, start_date=date(2026, 1, 1))
    return u


def test_edit_page_shows_ready_to_invite_panel(client):
    e = _special_event("panel-1")
    s = Speaker.objects.create(name="Derek Hook", slug="dh-panel", email="derek@x.test")
    e.speakers.add(s)
    client.force_login(_pc_user())
    resp = client.get(reverse("events:edit", args=[e.slug]))
    assert b"Ready to invite" in resp.content
    assert b"Derek Hook" in resp.content


def test_no_email_speaker_gets_no_panel(client):
    e = _special_event("panel-2")
    s = Speaker.objects.create(name="No Email", slug="no-email")
    e.speakers.add(s)
    client.force_login(_pc_user())
    resp = client.get(reverse("events:edit", args=[e.slug]))
    assert b"Ready to invite" not in resp.content


def test_confirm_send_invites(client):
    e = _special_event("panel-3")
    s = Speaker.objects.create(name="Derek Hook", slug="dh-send2", email="derek@x.test")
    e.speakers.add(s)
    client.force_login(_pc_user())
    resp = client.post(
        reverse("events:speaker_invite", args=[e.slug, s.pk]),
        {"message": "Please join us."}, follow=True,
    )
    assert resp.status_code == 200
    s.refresh_from_db()
    assert s.user is not None
    assert len(mail.outbox) == 1


def test_speaker_invite_forbidden_for_non_pc(client):
    e = _special_event("panel-4")
    s = Speaker.objects.create(name="Derek", slug="dh-forbid", email="derek@x.test")
    e.speakers.add(s)
    client.force_login(User.objects.create_user(email="rando@x.test"))
    resp = client.post(
        reverse("events:speaker_invite", args=[e.slug, s.pk]),
        {"message": "x"},
    )
    assert resp.status_code == 403
    s.refresh_from_db()
    assert s.user is None
