"""Tests for signup email verification and the bot defenses (task #471).

Covers the three layers added after the 2026-07-22 cutover brought a wave of
drive-by bot signups: proof of mailbox control before an account is usable,
invisible deterrents that reject before any mail is sent, and the purge of
never-verified rows.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from accounts import antibot
from accounts.models import EmailVerification, User

PW = "s3cret-pw!"


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    """The rate-limit counter lives in the process-wide locmem cache, which
    outlives a test transaction — without this, one test's attempts leak into
    the next and starve it of its allowance."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


def _form_data(**over):
    """A signup POST that passes the timing trap and leaves the honeypot empty."""
    data = {
        "email": "new@x.test",
        "first_name": "Ada",
        "last_name": "Lovelace",
        "password1": PW,
        "password2": PW,
        antibot.HONEYPOT_FIELD: "",
        antibot.TIMESTAMP_FIELD: antibot.sign_timestamp(
            when=timezone.now() - timedelta(seconds=30)
        ),
    }
    data.update(over)
    return data


# ---- The rendered form ------------------------------------------------


@pytest.mark.django_db
def test_signup_page_renders_the_bot_traps(client):
    resp = client.get(reverse("signup"))

    body = resp.content.decode()
    assert resp.status_code == 200
    # The honeypot ships inside its off-screen wrapper, not the visible loop.
    assert "hp-wrap" in body
    assert body.count(f'name="{antibot.HONEYPOT_FIELD}"') == 1
    assert f'name="{antibot.TIMESTAMP_FIELD}"' in body


# ---- Signup creates an unusable account --------------------------------


@pytest.mark.django_db
def test_signup_creates_inactive_user_and_does_not_log_in(client):
    resp = client.post(reverse("signup"), _form_data(), follow=True)

    user = User.objects.get(email="new@x.test")
    assert user.is_active is False
    assert user.profile.email_verified_at is None
    assert resp.wsgi_request.user.is_authenticated is False


@pytest.mark.django_db
def test_signup_emails_a_verification_link(client):
    client.post(reverse("signup"), _form_data())

    assert len(mail.outbox) == 1
    verification = EmailVerification.objects.get()
    assert verification.token in mail.outbox[0].body
    assert mail.outbox[0].to == ["new@x.test"]


# ---- Verification is scanner-safe --------------------------------------


@pytest.mark.django_db
def test_get_on_verify_url_does_not_consume_the_token(client):
    """Corporate/.gov link scanners pre-click; a GET must not burn the link."""
    client.post(reverse("signup"), _form_data())
    verification = EmailVerification.objects.get()

    client.get(reverse("signup_verify", args=[verification.token]))

    verification.refresh_from_db()
    assert verification.confirmed_at is None
    assert User.objects.get(email="new@x.test").is_active is False


@pytest.mark.django_db
def test_post_verifies_activates_and_logs_in(client):
    client.post(reverse("signup"), _form_data())
    verification = EmailVerification.objects.get()

    resp = client.post(
        reverse("signup_verify", args=[verification.token]), follow=True
    )

    user = User.objects.get(email="new@x.test")
    assert user.is_active is True
    assert user.profile.email_verified_at is not None
    assert resp.wsgi_request.user == user


@pytest.mark.django_db
def test_verification_honors_next_url_from_the_row(client):
    """The guest event funnel (task #464) must survive the mail round-trip,
    including opening the link on a different device."""
    client.post(
        reverse("signup") + "?next=/events/masochism/register/", _form_data()
    )
    verification = EmailVerification.objects.get()
    assert verification.next_url == "/events/masochism/register/"

    resp = client.post(reverse("signup_verify", args=[verification.token]))

    assert resp.url == "/events/masochism/register/"


@pytest.mark.django_db
def test_token_is_single_use(client):
    client.post(reverse("signup"), _form_data())
    verification = EmailVerification.objects.get()
    url = reverse("signup_verify", args=[verification.token])
    client.post(url)
    client.logout()

    resp = client.post(url)

    assert resp.status_code == 410


@pytest.mark.django_db
def test_expired_token_is_rejected(client):
    client.post(reverse("signup"), _form_data())
    verification = EmailVerification.objects.get()
    verification.created_at = timezone.now() - timedelta(days=4)
    verification.save(update_fields=["created_at"])

    resp = client.post(reverse("signup_verify", args=[verification.token]))

    assert resp.status_code == 410
    assert User.objects.get(email="new@x.test").is_active is False


# ---- Bot defenses ------------------------------------------------------


@pytest.mark.django_db
def test_honeypot_submission_creates_nothing_and_sends_no_mail(client):
    resp = client.post(
        reverse("signup"),
        _form_data(**{antibot.HONEYPOT_FIELD: "http://spam.test"}),
    )

    assert not User.objects.filter(email="new@x.test").exists()
    assert mail.outbox == []
    # Bots get no signal that they were caught.
    assert resp.status_code in (200, 302)


@pytest.mark.django_db
def test_submission_faster_than_two_seconds_is_rejected(client):
    resp = client.post(
        reverse("signup"),
        _form_data(**{antibot.TIMESTAMP_FIELD: antibot.sign_timestamp()}),
    )

    assert not User.objects.filter(email="new@x.test").exists()
    assert mail.outbox == []
    assert resp.status_code == 200


@pytest.mark.django_db
def test_rate_limit_blocks_the_sixth_signup_from_one_ip(client):
    for i in range(5):
        client.post(reverse("signup"), _form_data(email=f"u{i}@x.test"))
    assert User.objects.count() == 5

    resp = client.post(reverse("signup"), _form_data(email="over@x.test"))

    assert not User.objects.filter(email="over@x.test").exists()
    assert resp.status_code == 200


# ---- Grandfathering and purge ------------------------------------------


@pytest.mark.django_db
def test_purge_removes_only_stale_unverified_accounts():
    from django.core.management import call_command

    stale_bot = User.objects.create_user(
        email="bot@x.test", password=PW, is_active=False
    )
    User.objects.filter(pk=stale_bot.pk).update(
        date_joined=timezone.now() - timedelta(days=8)
    )
    User.objects.create_user(email="recent@x.test", password=PW, is_active=False)
    deactivated_member = User.objects.create_user(
        email="member@x.test", password=PW, is_active=False
    )
    deactivated_member.profile.email_verified_at = timezone.now()
    deactivated_member.profile.save(update_fields=["email_verified_at"])
    User.objects.filter(pk=deactivated_member.pk).update(
        date_joined=timezone.now() - timedelta(days=400)
    )

    call_command("purge_unverified_signups")

    assert not User.objects.filter(email="bot@x.test").exists()
    assert User.objects.filter(email="recent@x.test").exists()
    assert User.objects.filter(email="member@x.test").exists()


@pytest.mark.django_db
def test_unverified_login_attempt_offers_a_resend(client):
    client.post(reverse("signup"), _form_data())
    mail.outbox.clear()

    resp = client.post(
        reverse("login"), {"username": "new@x.test", "password": PW}
    )

    assert b"resend" in resp.content.lower()
