"""Transport-level deterrents on the public Find-an-Analyst form (#479).

A caught bot must get the ordinary success page: no ReferralRequest, no
mail, and no hint about which check burned it.
"""

from datetime import timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from accounts import antibot
from referrals.models import BlockedSubmission, ReferralRequest

pytestmark = pytest.mark.django_db


def _payload(**overrides):
    data = {
        "name": "Tina",
        "pronouns": "she/her",
        "pronouns_other": "",
        "email": "tina@example.com",
        "location": "San Antonio Texas",
        "language": "English",
        "modality": ["video"],
        "additional_information": (
            "I am looking for an analyst to help me work through a "
            "difficult period of caregiving and some longstanding grief."
        ),
        antibot.HONEYPOT_FIELD: "",
        antibot.TIMESTAMP_FIELD: antibot.sign_timestamp(
            timezone.now() - timedelta(seconds=60),
        ),
    }
    data.update(overrides)
    return data


def test_clean_submission_creates_a_request(client):
    resp = client.post(reverse("find_an_analyst"), _payload())
    assert resp.status_code == 302
    assert ReferralRequest.objects.count() == 1


def test_honeypot_filled_is_dropped_silently(client):
    resp = client.post(
        reverse("find_an_analyst"),
        _payload(**{antibot.HONEYPOT_FIELD: "http://spam.example.com"}),
    )
    assert resp.status_code == 302          # the ordinary success redirect
    assert ReferralRequest.objects.count() == 0
    assert mail.outbox == []
    assert BlockedSubmission.objects.filter(
        reason=BlockedSubmission.Reason.HONEYPOT,
    ).count() == 1


def test_too_fast_submission_is_dropped_silently(client):
    resp = client.post(
        reverse("find_an_analyst"),
        _payload(**{antibot.TIMESTAMP_FIELD: antibot.sign_timestamp()}),
    )
    assert resp.status_code == 302
    assert ReferralRequest.objects.count() == 0
    assert mail.outbox == []
    assert BlockedSubmission.objects.filter(
        reason=BlockedSubmission.Reason.TIMING,
    ).count() == 1


def test_missing_timestamp_is_dropped(client):
    resp = client.post(reverse("find_an_analyst"), _payload(**{
        antibot.TIMESTAMP_FIELD: "",
    }))
    assert resp.status_code == 302
    assert ReferralRequest.objects.count() == 0


def test_honeypot_is_a_text_input_not_a_hidden_input(client):
    # The whole incident: commodity bots skip type="hidden" on purpose.
    resp = client.get(reverse("find_an_analyst"))
    html = resp.content.decode()
    assert f'name="{antibot.HONEYPOT_FIELD}"' in html
    assert f'type="hidden" name="{antibot.HONEYPOT_FIELD}"' not in html
    assert "hp-wrap" in html


def test_looks_too_fast_takes_a_minimum():
    stamp = antibot.sign_timestamp(timezone.now() - timedelta(seconds=5))
    assert antibot.looks_too_fast(stamp, minimum=2) is False
    assert antibot.looks_too_fast(stamp, minimum=10) is True
