"""Held submissions never reach the referral list or the requester (#479)."""

import pytest
from django.core import mail

from referrals import services
from referrals.models import Mode, ReferralRequest, ReferralSettings

pytestmark = pytest.mark.django_db

JUNK = {
    "name": "LEIAZKMKtfUBswyJuaS",
    "pronouns": "IzNydkEnQFrKxxKl",
    "email": "lauren_michele2005@hotmail.com",
    "location": "lfNxcMPRAZNciaxtfNPOMQK",
    "language": "iIcIlrhZIIwEImoxJld",
    "modality": "In person, By phone, By online video platform",
    "additional_information": "GtDlqAgHoujeYbXggDwPs",
}

CLEAN = {
    "name": "Tina",
    "pronouns": "she/her",
    "email": "tina@example.com",
    "location": "San Antonio Texas",
    "language": "English",
    "modality": "By online video platform",
    "additional_information": (
        "I am looking for a therapist who can help me process some "
        "longstanding grief and the strain of caring for my father."
    ),
}


@pytest.fixture
def auto_everything():
    config = ReferralSettings.load()
    config.ack_mode = Mode.AUTO
    config.distribution_mode = Mode.AUTO
    config.save()
    return config


def test_junk_is_held_and_sends_nothing(auto_everything):
    req = services.intake(dict(JUNK))
    assert req.status == ReferralRequest.Status.HELD
    assert req.held_at is not None
    assert "name" in req.held_reason
    # Nothing to the harvested address, nothing to the referral list.
    assert mail.outbox == []
    assert req.distributed_at is None
    assert req.acknowledged_at is None


def test_clean_request_still_flows_automatically(auto_everything):
    req = services.intake(dict(CLEAN))
    assert req.status == ReferralRequest.Status.DISTRIBUTED
    assert req.acknowledged_at is not None
    assert req.distributed_at is not None


def test_distribute_refuses_a_held_request():
    req = services.intake(dict(JUNK))
    with pytest.raises(services.SuppressedStatusError):
        services.distribute(req)


def test_acknowledge_refuses_a_held_request():
    req = services.intake(dict(JUNK))
    with pytest.raises(services.SuppressedStatusError):
        services.send_acknowledgment(req)


def test_distribute_refuses_a_junk_request():
    req = services.intake(dict(CLEAN))
    req.status = ReferralRequest.Status.JUNK
    req.save(update_fields=["status"])
    with pytest.raises(services.SuppressedStatusError):
        services.distribute(req)


def test_release_resumes_the_normal_chain(auto_everything):
    req = services.intake(dict(JUNK))
    mail.outbox.clear()
    services.release(req)
    req.refresh_from_db()
    assert req.status == ReferralRequest.Status.DISTRIBUTED
    assert req.held_reason == ""
    assert req.held_at is None


def test_release_under_review_mode_only_clears_the_hold():
    config = ReferralSettings.load()
    config.ack_mode = Mode.REVIEW
    config.distribution_mode = Mode.REVIEW
    config.save()
    req = services.intake(dict(JUNK))
    services.release(req)
    req.refresh_from_db()
    assert req.status == ReferralRequest.Status.NEW
    assert req.distributed_at is None
