"""CE intent on the event proposal (task #486)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import Profile, User
from events.ce import CECreditBasis
from events.models import Event, EventProposal

# Every propose POST carries these: submit intent (vs save), the location
# dropdown, and the external-speaker formset's management form. Copied from
# events/test_event_proposal.py::_MGMT — keep the two in step.
_MGMT = {
    "action": "submit",
    "location_kind": "online_insite",
    "speakers-TOTAL_FORMS": "0", "speakers-INITIAL_FORMS": "0",
    "speakers-MIN_NUM_FORMS": "0", "speakers-MAX_NUM_FORMS": "1000",
}


@pytest.fixture
def proposer(db):
    u = User.objects.create_user(email="proposer-ce@x.test", password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.is_faculty = True
    u.profile.save()
    return u


@pytest.mark.django_db
def test_proposal_form_accepts_a_credit_estimate(client, proposer):
    client.force_login(proposer)
    response = client.post(reverse("propose_event"), {
        **_MGMT,
        "event_type": Event.Type.SEMINAR,
        "title": "Seminar on Anxiety",
        "description": "A year with Seminar X.",
        "start_date": "2026-09-01",
        "end_date": "2027-05-01",
        "fee_type": "free",
        "schedule_choice": "tbd",
        "offers_ce": "on",
        "ce_credits": "2",
        "ce_credits_basis": CECreditBasis.PER_MEETING,
    })
    assert response.status_code == 302
    proposal = EventProposal.objects.get(title="Seminar on Anxiety")
    assert proposal.offers_ce is True
    assert proposal.ce_credits == Decimal("2")
    assert proposal.ce_credits_basis == CECreditBasis.PER_MEETING


@pytest.mark.django_db
def test_the_estimate_is_optional(client, proposer):
    client.force_login(proposer)
    response = client.post(reverse("propose_event"), {
        **_MGMT,
        "event_type": Event.Type.SEMINAR,
        "title": "Seminar on Transference",
        "description": "A year with Seminar VIII.",
        "start_date": "2026-09-01",
        "end_date": "2027-05-01",
        "fee_type": "free",
        "schedule_choice": "tbd",
        "offers_ce": "on",
    })
    assert response.status_code == 302
    proposal = EventProposal.objects.get(title="Seminar on Transference")
    assert proposal.offers_ce is True
    assert proposal.ce_credits is None
    assert proposal.ce_credits_label == "CE credits available."
