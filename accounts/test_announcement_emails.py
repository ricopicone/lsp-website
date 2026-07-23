"""Keyed announcement emails: dry-run default, per-key dedupe, exclusions."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command

from accounts.models import AnnouncementEmail

User = get_user_model()


@pytest.fixture(autouse=True)
def _fast_sender(settings):
    settings.EMAIL_MAX_SEND_RATE = 1000.0


@pytest.fixture
def members(db):
    a = User.objects.create_user(email="amy@example.com", password="x")
    b = User.objects.create_user(email="bo@example.com", password="x")
    return a, b


@pytest.mark.django_db
def test_unknown_key_rejected(members):
    with pytest.raises(CommandError):
        call_command("send_announcement_emails", "--key", "nope")


@pytest.mark.django_db
def test_dry_run_sends_nothing(members, mailoutbox):
    call_command("send_announcement_emails", "--key", "site-launch-2026")
    assert len(mailoutbox) == 0
    assert AnnouncementEmail.objects.count() == 0


@pytest.mark.django_db
def test_commit_sends_and_keys_are_independent(members, mailoutbox, settings):
    settings.SITE_BASE_URL = "https://lacanschool.org"
    call_command("send_announcement_emails", "--key", "site-launch-2026", "--commit")
    assert len(mailoutbox) == 2
    assert "unveil" in mailoutbox[0].body

    # Same key re-run: silent. Different key: sends again.
    mailoutbox.clear()
    call_command("send_announcement_emails", "--key", "site-launch-2026", "--commit")
    assert len(mailoutbox) == 0
    call_command("send_announcement_emails", "--key", "program-2026-2027", "--commit")
    assert len(mailoutbox) == 2
    assert "2026–2027" in mailoutbox[0].subject
    assert "https://lacanschool.org/program/" in mailoutbox[0].body
    assert "https://lacanschool.org/guides/seminars/" in mailoutbox[0].body


@pytest.mark.django_db
def test_only_and_persona_exclusion(members, mailoutbox):
    a, b = members
    b.profile.is_persona = True
    b.profile.save(update_fields=["is_persona"])
    call_command(
        "send_announcement_emails", "--key", "site-launch-2026",
        "--commit", "--only", "AMY@example.com,bo@example.com",
    )
    assert [m.to[0] for m in mailoutbox] == ["amy@example.com"]
