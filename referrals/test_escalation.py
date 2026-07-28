"""Stale-hold escalation and counter pruning (#479)."""

from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from referrals import services
from referrals.models import BlockedSubmission, ReferralRequest, ReferralSettings

pytestmark = pytest.mark.django_db


def _held(age_days: int) -> ReferralRequest:
    req = ReferralRequest.objects.create(
        name="Maybe Real", email="person@example.com", location="Pittsburgh",
        language="English", status=ReferralRequest.Status.HELD,
        held_reason="The description is too short (12 characters).",
    )
    ReferralRequest.objects.filter(pk=req.pk).update(
        held_at=timezone.now() - timedelta(days=age_days),
    )
    req.refresh_from_db()
    return req


def test_fresh_hold_is_not_escalated():
    _held(age_days=1)
    assert services.escalate_stale_holds() == 0
    assert mail.outbox == []


def test_stale_hold_is_escalated_once():
    req = _held(age_days=5)
    assert services.escalate_stale_holds() == 1
    assert len(mail.outbox) == 1
    req.refresh_from_db()
    assert req.held_escalated_at is not None
    # Second run must not re-send.
    assert services.escalate_stale_holds() == 0
    assert len(mail.outbox) == 1


def test_escalation_has_no_reply_to_the_suspected_bot():
    # A held request may be a bot using a stranger's harvested address;
    # replying to it is the unsolicited mail the hold exists to prevent.
    req = _held(age_days=5)
    services.escalate_stale_holds()
    assert req.email not in (mail.outbox[0].reply_to or [])


def test_released_hold_is_not_escalated():
    req = _held(age_days=5)
    req.status = ReferralRequest.Status.NEW
    req.save(update_fields=["status"])
    assert services.escalate_stale_holds() == 0


def test_escalation_threshold_follows_settings():
    config = ReferralSettings.load()
    config.held_escalation_days = 10
    config.save()
    _held(age_days=5)
    assert services.escalate_stale_holds() == 0


def test_prune_drops_rows_over_a_year_old():
    old = BlockedSubmission.objects.create(
        reason=BlockedSubmission.Reason.HONEYPOT,
    )
    BlockedSubmission.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(days=400),
    )
    BlockedSubmission.objects.create(reason=BlockedSubmission.Reason.TIMING)
    assert services.prune_blocked_submissions() == 1
    assert BlockedSubmission.objects.count() == 1
