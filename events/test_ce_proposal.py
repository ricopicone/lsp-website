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
def test_a_special_event_can_declare_ce_intent(client, proposer):
    """A visiting speaker's day is among the likeliest things to carry CE, so
    the CE block is not restricted to the annual-program offerings."""
    client.force_login(proposer)
    response = client.post(reverse("propose_event"), {
        **_MGMT,
        "event_type": Event.Type.SPECIAL_EVENT,
        "title": "A Day on Masochism",
        "description": "A one-day event with a visiting speaker.",
        "date_tbd": "on",
        "fee_type": "free",
        "offers_ce": "on",
        "ce_credits": "6",
        "ce_credits_basis": CECreditBasis.TOTAL,
    })
    assert response.status_code == 302
    proposal = EventProposal.objects.get(title="A Day on Masochism")
    assert proposal.offers_ce is True
    assert proposal.ce_credits == Decimal("6")
    assert proposal.ce_credits_label == "Approved for 6 CE credits."


@pytest.mark.django_db
def test_the_ce_fields_are_shown_for_every_proposable_type(client, proposer):
    """The per-type show/hide is driven by data-types attributes, so the CE
    field block must list special_event alongside the offerings."""
    client.force_login(proposer)
    body = client.get(reverse("propose_event")).content.decode()
    checkbox = body.index('id="id_offers_ce"')
    # The nearest data-types attribute before the checkbox is the block that
    # governs whether it's shown.
    start = body.rindex('data-types="', 0, checkbox) + len('data-types="')
    types = body[start:body.index('"', start)].split()
    assert set(types) == {"seminar", "reading_group", "special_event"}


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
