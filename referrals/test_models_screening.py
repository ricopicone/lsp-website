import pytest

from referrals.models import BlockedSubmission, ReferralRequest, ReferralSettings

pytestmark = pytest.mark.django_db


def test_held_and_junk_statuses_exist():
    assert ReferralRequest.Status.HELD == "held"
    assert ReferralRequest.Status.JUNK == "junk"


def test_suppressed_statuses_cover_held_and_junk():
    assert set(ReferralRequest.SUPPRESSED_STATUSES) == {
        ReferralRequest.Status.HELD, ReferralRequest.Status.JUNK,
    }


def test_open_statuses_exclude_held_and_junk():
    # HELD is the coordinator's problem but must not enter the normal
    # workflow, or process_referrals would try to follow it up.
    assert ReferralRequest.Status.HELD not in ReferralRequest.OPEN_STATUSES
    assert ReferralRequest.Status.JUNK not in ReferralRequest.OPEN_STATUSES


def test_held_fields_default_empty():
    req = ReferralRequest.objects.create(
        name="Tina", email="t@example.com", location="Texas", language="English",
    )
    assert req.held_reason == ""
    assert req.held_at is None
    assert req.held_escalated_at is None


def test_blocked_submission_stores_no_content():
    row = BlockedSubmission.objects.create(
        reason=BlockedSubmission.Reason.HONEYPOT,
    )
    assert row.created_at is not None
    # The whole point: nothing identifying, nothing to leak.
    field_names = {f.name for f in BlockedSubmission._meta.get_fields()}
    assert field_names == {"id", "created_at", "reason"}


def test_settings_has_escalation_days_default():
    assert ReferralSettings.load().held_escalation_days == 3
