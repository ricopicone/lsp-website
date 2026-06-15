"""Friendly From headers: a site-wide display name, with per-type overrides."""

from __future__ import annotations

from django.conf import settings

from core.email import school_from


def test_default_from_carries_school_name():
    # settings wraps the bare address with EMAIL_FROM_NAME.
    assert settings.EMAIL_FROM_NAME in settings.DEFAULT_FROM_EMAIL
    assert settings.DEFAULT_FROM_ADDRESS in settings.DEFAULT_FROM_EMAIL


def test_school_from_default_and_override():
    assert school_from().startswith(settings.EMAIL_FROM_NAME + " <")
    named = school_from("LSP Referral Coordinator")
    assert named.startswith("LSP Referral Coordinator <")
    assert settings.DEFAULT_FROM_ADDRESS in named


def test_referral_email_from_and_reply_to(db, settings):
    from django.core import mail

    settings.REFERRALS_EMAIL = "referrals@lacanschool.org"
    from referrals import emails

    emails.send_to_clinician(
        type("U", (), {"email": "c@example.com"})(), "Subject", "Body"
    )
    msg = mail.outbox[-1]
    assert "LSP Referral Coordinator" in msg.from_email
    assert msg.reply_to == ["referrals@lacanschool.org"]
