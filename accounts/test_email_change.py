"""Tests for the self-service login-email change flow (verify-before-switch):
gating, initiation (re-auth + uniqueness), and token confirmation.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import EmailChangeRequest, User

PW = "s3cret-pw!"


def _user(email, allow_settings, password=PW):
    u = User.objects.create_user(email=email, password=password)
    allow_settings.EMAIL_CHANGE_PUBLIC = False
    allow_settings.EMAIL_CHANGE_ALLOWLIST = [email]
    return u


# ---- Gating ------------------------------------------------------------


@pytest.mark.django_db
def test_gate_blocks_non_allowlisted(client, settings):
    settings.EMAIL_CHANGE_PUBLIC = False
    settings.EMAIL_CHANGE_ALLOWLIST = ["someone-else@x.test"]
    u = User.objects.create_user(email="nope@x.test", password=PW)
    client.force_login(u)
    assert client.get(reverse("email_change")).status_code == 404


@pytest.mark.django_db
def test_gate_allows_allowlisted(client, settings):
    u = _user("vip@x.test", settings)
    client.force_login(u)
    assert client.get(reverse("email_change")).status_code == 200


@pytest.mark.django_db
def test_gate_public_flag_opens_to_all(client, settings):
    settings.EMAIL_CHANGE_PUBLIC = True
    settings.EMAIL_CHANGE_ALLOWLIST = []
    u = User.objects.create_user(email="anyone@x.test", password=PW)
    client.force_login(u)
    assert client.get(reverse("email_change")).status_code == 200


# ---- Initiation --------------------------------------------------------


@pytest.mark.django_db
def test_initiate_creates_request_and_emails_new_address(client, settings, mailoutbox):
    u = _user("old@x.test", settings)
    client.force_login(u)
    resp = client.post(reverse("email_change"), {
        "new_email": "new@x.test", "password": PW,
    })
    assert resp.status_code == 200
    req = EmailChangeRequest.objects.get(user=u)
    assert req.new_email == "new@x.test"
    assert req.confirmed_at is None
    # Login email is unchanged until confirmation.
    u.refresh_from_db()
    assert u.email == "old@x.test"
    # Verification email went to the NEW address and carries the link.
    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == ["new@x.test"]
    assert req.token in mailoutbox[0].body


@pytest.mark.django_db
def test_initiate_rejects_wrong_password(client, settings, mailoutbox):
    u = _user("pw@x.test", settings)
    client.force_login(u)
    resp = client.post(reverse("email_change"), {
        "new_email": "new@x.test", "password": "wrong",
    })
    assert resp.status_code == 200
    assert b"incorrect" in resp.content
    assert not EmailChangeRequest.objects.exists()
    assert mailoutbox == []


@pytest.mark.django_db
def test_initiate_rejects_taken_email(client, settings, mailoutbox):
    u = _user("me@x.test", settings)
    User.objects.create_user(email="taken@x.test", password=PW)
    client.force_login(u)
    resp = client.post(reverse("email_change"), {
        "new_email": "taken@x.test", "password": PW,
    })
    assert b"already exists" in resp.content
    assert not EmailChangeRequest.objects.exists()
    assert mailoutbox == []


@pytest.mark.django_db
def test_initiate_rejects_same_email(client, settings):
    u = _user("same@x.test", settings)
    client.force_login(u)
    resp = client.post(reverse("email_change"), {
        "new_email": "SAME@x.test", "password": PW,  # case-insensitive
    })
    assert b"already your login email" in resp.content
    assert not EmailChangeRequest.objects.exists()


@pytest.mark.django_db
def test_initiate_supersedes_prior_pending(client, settings, mailoutbox):
    u = _user("sup@x.test", settings)
    stale = EmailChangeRequest.objects.create(user=u, new_email="first@x.test")
    client.force_login(u)
    client.post(reverse("email_change"), {"new_email": "second@x.test", "password": PW})
    assert not EmailChangeRequest.objects.filter(pk=stale.pk).exists()
    assert EmailChangeRequest.objects.filter(user=u).count() == 1


# ---- Confirmation ------------------------------------------------------


@pytest.mark.django_db
def test_confirm_switches_email_and_notifies_old(client, mailoutbox):
    u = User.objects.create_user(email="before@x.test", password=PW)
    req = EmailChangeRequest.objects.create(user=u, new_email="after@x.test")
    resp = client.get(reverse("email_change_confirm", args=[req.token]))
    assert resp.status_code == 200
    u.refresh_from_db()
    assert u.email == "after@x.test"
    req.refresh_from_db()
    assert req.confirmed_at is not None
    # Security notice goes to the OLD address.
    assert any(m.to == ["before@x.test"] for m in mailoutbox)


@pytest.mark.django_db
def test_confirm_rejects_expired(client):
    u = User.objects.create_user(email="exp@x.test", password=PW)
    req = EmailChangeRequest.objects.create(user=u, new_email="late@x.test")
    EmailChangeRequest.objects.filter(pk=req.pk).update(
        created_at=timezone.now() - timedelta(hours=25)
    )
    resp = client.get(reverse("email_change_confirm", args=[req.token]))
    assert b"expired" in resp.content
    u.refresh_from_db()
    assert u.email == "exp@x.test"


@pytest.mark.django_db
def test_confirm_token_is_single_use(client):
    u = User.objects.create_user(email="once@x.test", password=PW)
    req = EmailChangeRequest.objects.create(user=u, new_email="done@x.test")
    client.get(reverse("email_change_confirm", args=[req.token]))
    # Second use is rejected (already confirmed) and doesn't re-change anything.
    resp = client.get(reverse("email_change_confirm", args=[req.token]))
    assert b"invalid or has already been used" in resp.content


@pytest.mark.django_db
def test_confirm_rejects_when_address_taken_in_race(client):
    u = User.objects.create_user(email="racer@x.test", password=PW)
    req = EmailChangeRequest.objects.create(user=u, new_email="contested@x.test")
    # Someone else grabs the address between request and confirmation.
    User.objects.create_user(email="contested@x.test", password=PW)
    resp = client.get(reverse("email_change_confirm", args=[req.token]))
    assert b"now in use" in resp.content
    u.refresh_from_db()
    assert u.email == "racer@x.test"


@pytest.mark.django_db
def test_confirm_invalid_token(client):
    resp = client.get(reverse("email_change_confirm", args=["bogus-token"]))
    assert resp.status_code == 200
    assert b"invalid" in resp.content
