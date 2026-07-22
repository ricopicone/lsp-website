"""The launch welcome email: dry-run default, send-once tracking, exclusions."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from accounts.models import WelcomeEmail

User = get_user_model()


@pytest.fixture(autouse=True)
def _fast_sender(settings):
    settings.EMAIL_MAX_SEND_RATE = 1000.0


@pytest.fixture
def members(db):
    a = User.objects.create_user(email="ada@example.com", password="x")
    b = User.objects.create_user(email="ben@example.com", password="x")
    return a, b


@pytest.mark.django_db
def test_dry_run_sends_nothing(members, mailoutbox):
    call_command("send_welcome_emails")
    assert len(mailoutbox) == 0
    assert WelcomeEmail.objects.count() == 0


@pytest.mark.django_db
def test_commit_sends_records_and_links_the_guide(members, mailoutbox, settings):
    settings.SITE_BASE_URL = "https://lacanschool.org"
    call_command("send_welcome_emails", "--commit")
    assert {m.to[0] for m in mailoutbox} == {"ada@example.com", "ben@example.com"}
    assert WelcomeEmail.objects.count() == 2
    body = mailoutbox[0].body
    assert "https://lacanschool.org/guides/logging-in/" in body
    assert "https://lacanschool.org/accounts/login/" in body


@pytest.mark.django_db
def test_rerun_skips_already_welcomed(members, mailoutbox):
    call_command("send_welcome_emails", "--commit")
    mailoutbox.clear()
    call_command("send_welcome_emails", "--commit")
    assert len(mailoutbox) == 0


@pytest.mark.django_db
def test_personas_and_inactive_excluded(members, mailoutbox):
    a, b = members
    a.profile.is_persona = True
    a.profile.save(update_fields=["is_persona"])
    b.is_active = False
    b.save(update_fields=["is_active"])
    call_command("send_welcome_emails", "--commit")
    assert len(mailoutbox) == 0


@pytest.mark.django_db
def test_only_restricts_recipients(members, mailoutbox):
    call_command("send_welcome_emails", "--commit", "--only", "ADA@example.com")
    assert [m.to[0] for m in mailoutbox] == ["ada@example.com"]
    assert WelcomeEmail.objects.filter(user__email="ben@example.com").count() == 0
