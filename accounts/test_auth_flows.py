"""Tests for the email-based auth additions:

- password reset (Django built-in, wired under accounts/ with Reply-To)
- passwordless magic-link sign-in
- admin TOTP 2FA: enrollment, challenge, recovery codes, and the
  enforcement middleware (gated off by default).
"""

from __future__ import annotations

import re
from datetime import timedelta

import pyotp
import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from accounts import twofactor
from accounts.models import MagicLoginLink, TOTPDevice, User

PW = "s3cret-pw!"


def _user(email="m@x.test", **kw):
    return User.objects.create_user(email=email, password=PW, **kw)


def _admin(email="admin@x.test"):
    # is_staff makes can_access_admin_tools() true → requires_2fa() true.
    return User.objects.create_user(email=email, password=PW, is_staff=True)


# ---- Password reset ----------------------------------------------------


@pytest.mark.django_db
def test_password_reset_emails_link_with_reply_to(client, settings):
    settings.SUPPORT_EMAIL = "help@lacanschool.org"
    u = _user("reset-me@x.test")
    resp = client.post(reverse("password_reset"), {"email": u.email})
    assert resp.status_code == 302
    assert len(mail.outbox) == 1
    assert mail.outbox[0].reply_to == [settings.SUPPORT_EMAIL]
    assert re.search(r"/accounts/reset/[^/]+/[^/\s]+/", mail.outbox[0].body)


@pytest.mark.django_db
def test_password_reset_completes_and_logs_in(client):
    u = _user("reset-flow@x.test")
    client.post(reverse("password_reset"), {"email": u.email})
    path = re.search(r"/accounts/reset/[^/]+/[^/\s]+/", mail.outbox[0].body).group(0)
    # GET stores the token in the session and redirects to the set-password URL.
    resp = client.get(path, follow=True)
    assert resp.status_code == 200
    post_url = resp.redirect_chain[-1][0]
    new = "Totally-New-Pass-9!"
    resp = client.post(post_url, {"new_password1": new, "new_password2": new})
    assert resp.status_code == 302
    u.refresh_from_db()
    assert u.check_password(new)


@pytest.mark.django_db
def test_password_reset_unknown_email_sends_nothing_but_succeeds(client):
    resp = client.post(reverse("password_reset"), {"email": "ghost@x.test"})
    assert resp.status_code == 302  # same "done" redirect — no enumeration
    assert mail.outbox == []


@pytest.mark.django_db
def test_login_page_shows_reset_and_magic_links(client):
    body = client.get(reverse("login")).content.decode()
    assert reverse("password_reset") in body
    assert reverse("magic_link_request") in body


# ---- Magic-link sign-in ------------------------------------------------


@pytest.mark.django_db
def test_magic_link_sends_for_existing_user(client):
    u = _user("magic@x.test")
    resp = client.post(reverse("magic_link_request"), {"email": "MAGIC@x.test"})
    assert resp.status_code == 200
    assert MagicLoginLink.objects.filter(user=u).count() == 1
    assert len(mail.outbox) == 1
    link = MagicLoginLink.objects.get(user=u)
    assert link.token in mail.outbox[0].body


@pytest.mark.django_db
def test_magic_link_unknown_email_no_enumeration(client):
    resp = client.post(reverse("magic_link_request"), {"email": "nobody@x.test"})
    assert resp.status_code == 200
    assert "emailed a sign-in link" in resp.content.decode()
    assert mail.outbox == []
    assert MagicLoginLink.objects.count() == 0


@pytest.mark.django_db
def test_magic_link_repeat_reuses_unexpired_link(client):
    _user("repeat@x.test")
    client.post(reverse("magic_link_request"), {"email": "repeat@x.test"})
    client.post(reverse("magic_link_request"), {"email": "repeat@x.test"})
    assert MagicLoginLink.objects.count() == 1  # reused, not minted twice


@pytest.mark.django_db
def test_magic_link_consume_logs_in_and_is_single_use(client):
    u = _user("consume@x.test")
    link = MagicLoginLink.objects.create(user=u)
    resp = client.get(reverse("magic_link_consume", args=[link.token]))
    assert resp.status_code == 302
    assert "_auth_user_id" in client.session
    link.refresh_from_db()
    assert link.used_at is not None
    # Replay rejected.
    client.logout()
    resp = client.get(reverse("magic_link_consume", args=[link.token]))
    assert resp.status_code == 410
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_magic_link_expired_rejected(client):
    u = _user("stale@x.test")
    link = MagicLoginLink.objects.create(user=u)
    MagicLoginLink.objects.filter(pk=link.pk).update(
        created_at=timezone.now() - timedelta(minutes=20)
    )
    resp = client.get(reverse("magic_link_consume", args=[link.token]))
    assert resp.status_code == 410


# ---- 2FA: eligibility + enrollment -------------------------------------


@pytest.mark.django_db
def test_requires_2fa_only_for_admins():
    assert twofactor.requires_2fa(_admin()) is True
    assert twofactor.requires_2fa(_user("plain@x.test")) is False


@pytest.mark.django_db
def test_totp_enrollment_confirms_and_mints_recovery_codes(client):
    admin = _admin()
    client.force_login(admin)
    resp = client.get(reverse("twofactor_setup"))
    assert resp.status_code == 200
    device = TOTPDevice.objects.get(user=admin)
    assert device.confirmed is False
    code = pyotp.TOTP(device.secret).now()
    resp = client.post(reverse("twofactor_setup"), {"code": code})
    assert resp.status_code == 302
    assert resp.url == reverse("twofactor_recovery")
    device.refresh_from_db()
    assert device.confirmed is True
    assert device.recovery_codes.count() == twofactor.RECOVERY_CODE_COUNT
    # Recovery page shows the plaintext once, then clears it from the session.
    page = client.get(reverse("twofactor_recovery"))
    assert page.status_code == 200
    assert client.get(reverse("twofactor_recovery")).status_code == 302


@pytest.mark.django_db
def test_totp_enrollment_rejects_bad_code(client):
    admin = _admin()
    client.force_login(admin)
    client.get(reverse("twofactor_setup"))
    resp = client.post(reverse("twofactor_setup"), {"code": "000000"})
    assert resp.status_code == 200
    assert TOTPDevice.objects.get(user=admin).confirmed is False


# ---- 2FA: enforcement middleware ---------------------------------------


@pytest.mark.django_db
def test_enforcement_off_admin_not_challenged(client, settings):
    settings.TWO_FACTOR_ENFORCED = False
    admin = _admin()
    client.force_login(admin)
    assert client.get("/").status_code == 200


@pytest.mark.django_db
def test_enforcement_on_forces_enrollment(client, settings):
    settings.TWO_FACTOR_ENFORCED = True
    admin = _admin()
    client.force_login(admin)
    resp = client.get("/")
    assert resp.status_code == 302
    assert resp.url == reverse("twofactor_setup")


@pytest.mark.django_db
def test_enforcement_on_non_admin_untouched(client, settings):
    settings.TWO_FACTOR_ENFORCED = True
    client.force_login(_user("normal@x.test"))
    assert client.get("/").status_code == 200


def _enroll(client, admin):
    device = TOTPDevice.objects.create(
        user=admin, secret=twofactor.new_secret(), confirmed=True
    )
    return device


@pytest.mark.django_db
def test_enforcement_on_confirmed_device_requires_challenge(client, settings):
    settings.TWO_FACTOR_ENFORCED = True
    admin = _admin()
    device = _enroll(client, admin)
    client.force_login(admin)  # fresh session: not yet verified
    resp = client.get("/")
    assert resp.status_code == 302
    assert reverse("twofactor_verify") in resp.url
    # Pass the challenge → session flagged → through.
    code = pyotp.TOTP(device.secret).now()
    resp = client.post(reverse("twofactor_verify"), {"code": code})
    assert resp.status_code == 302
    assert client.session.get(twofactor.SESSION_VERIFIED_KEY) is True
    assert client.get("/").status_code == 200


@pytest.mark.django_db
def test_recovery_code_passes_challenge_once(client, settings):
    settings.TWO_FACTOR_ENFORCED = True
    admin = _admin()
    device = _enroll(client, admin)
    codes = twofactor.generate_recovery_codes(device)
    client.force_login(admin)
    resp = client.post(reverse("twofactor_verify"), {"code": codes[0]})
    assert resp.status_code == 302
    assert client.session.get(twofactor.SESSION_VERIFIED_KEY) is True
    # The consumed code no longer works on a fresh session.
    client.logout()
    client.force_login(admin)
    resp = client.post(reverse("twofactor_verify"), {"code": codes[0]})
    assert resp.status_code == 200  # rejected, re-renders the form


@pytest.mark.django_db
def test_auth_pages_reachable_while_unverified(client, settings):
    settings.TWO_FACTOR_ENFORCED = True
    admin = _admin()
    _enroll(client, admin)
    client.force_login(admin)  # unverified
    # Exempt flows must not bounce to the challenge.
    assert client.get(reverse("password_reset")).status_code == 200
    assert client.get(reverse("twofactor_verify")).status_code == 200
