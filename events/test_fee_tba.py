"""A save-the-date: a special event published before its fee is set (task #769).

The fee was never a required field, but "Free" was the default, so a PC member
publishing a date and description ahead of the fee got a "$0.00" price table
and an open Register button. "To be announced" is the honest third state: the
page is live, it says the fee is coming, and registration can't open until a
fee is chosen.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import User
from events.forms import EventEditForm, EventProposalForm
from events.models import Event, PriceTier
from events.price_spec import PriceSpec, apply_to_event, from_event, label
from events.registration_status import open_refusal, set_registration_status
from events.test_program_admin import _special_event_payload
from events.test_program_admin import pc_member as pc_member  # noqa: F401  (fixture)
from registrations.models import Registration

pytestmark = pytest.mark.django_db


def _special(**kw):
    defaults = dict(
        title="Izcovich Seminar", slug="izcovich-seminar",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2030, 11, 5), end_date=date(2030, 11, 5),
        published=True, status=Event.Status.OPEN,
    )
    defaults.update(kw)
    return Event.objects.create(**defaults)


def _edit_data(event, **overrides):
    data = {"title": event.title, "description": event.description or "About."}
    data.update(overrides)
    return data


# --- Direct create ------------------------------------------------------


def test_direct_create_tba_publishes_with_registration_not_open(client, pc_member):
    client.force_login(pc_member)
    resp = client.post(
        reverse("program_admin_special_event_new"),
        _special_event_payload(action="publish", fee_type="tba"),
    )
    assert resp.status_code == 302
    e = Event.objects.get(event_type=Event.Type.SPECIAL_EVENT)
    assert e.published is True
    assert e.fee_tba is True
    assert e.status == Event.Status.DRAFT
    assert not e.price_tiers.exists()


def test_public_page_says_to_be_announced_and_offers_no_register(client):
    e = _special(fee_tba=True, status=Event.Status.DRAFT)
    resp = client.get(reverse("events:detail", args=[e.slug]))
    body = resp.content.decode()
    assert "To be announced." in body
    assert "It opens once the fee is announced." in body
    assert 'id="register-cta"' not in body
    assert "$0.00" not in body


def test_tba_is_not_offered_to_offerings():
    form = EventProposalForm(data={
        "event_type": "seminar", "title": "S", "description": "d",
        "fee_type": "tba",
    })
    form.is_valid()
    assert "fee_type" in form.errors


# --- Price spec -----------------------------------------------------------


def test_spec_round_trips_and_labels():
    spec = PriceSpec(tuition_covers=False, tba=True)
    assert spec.fee_type == "tba"
    assert PriceSpec.from_dict(spec.to_dict()) == spec
    assert label(spec) == "To be announced"


def test_applying_tba_drops_the_tier_and_takes_back_open_registration():
    e = _special()
    apply_to_event(e, PriceSpec(amount=Decimal("100"), tuition_covers=False))
    assert e.price_tiers.count() == 1
    apply_to_event(e, PriceSpec(tuition_covers=False, tba=True))
    e.refresh_from_db()
    assert e.fee_tba is True
    assert e.status == Event.Status.DRAFT
    assert not e.price_tiers.exists()
    assert from_event(e).fee_type == "tba"


def test_setting_a_fee_clears_tba_but_leaves_registration_to_the_pc():
    e = _special(fee_tba=True, status=Event.Status.DRAFT)
    apply_to_event(e, PriceSpec(amount=Decimal("150"), tuition_covers=True))
    e.refresh_from_db()
    assert e.fee_tba is False
    assert e.price_tiers.get().base_amount == Decimal("150")
    # Opening is still a deliberate act.
    assert e.status == Event.Status.DRAFT


# --- Edit form --------------------------------------------------------------


def test_edit_form_prefills_tba_and_keeps_it():
    e = _special(fee_tba=True, status=Event.Status.DRAFT)
    form = EventEditForm(instance=e)
    assert form.initial["fee_type"] == "tba"
    form = EventEditForm(_edit_data(e, fee_type="tba"), instance=e)
    assert form.is_valid(), form.errors
    form.save()
    form.save_price(e)
    e.refresh_from_db()
    assert e.fee_tba is True


def test_edit_form_hides_tba_for_a_seminar():
    e = _special(event_type=Event.Type.SEMINAR, slug="a-seminar")
    values = [v for v, _ in EventEditForm(instance=e).fields["fee_type"].choices]
    assert "tba" not in values


def test_edit_form_refuses_tba_once_someone_has_registered():
    e = _special()
    tier = PriceTier.objects.create(event=e, base_amount=Decimal("100"))
    u = User.objects.create_user(email="r@x.test", password="x")
    Registration.objects.create(
        event=e, user=u, price_tier=tier, quoted_amount=Decimal("100"),
        status=Registration.Status.PAID,
    )
    form = EventEditForm(_edit_data(e, fee_type="tba"), instance=e)
    assert not form.is_valid()
    assert "fee_type" in form.errors


# --- Opening registration ----------------------------------------------------


def test_registration_cannot_open_while_fee_is_tba():
    e = _special(fee_tba=True, status=Event.Status.DRAFT)
    assert open_refusal(e)
    assert set_registration_status(e, "open") is None
    e.refresh_from_db()
    assert e.status == Event.Status.DRAFT
    # Closing is never refused.
    assert open_refusal(_special(slug="other")) is None


def test_pc_open_button_refuses_with_a_reason(client, pc_member):
    e = _special(fee_tba=True, status=Event.Status.DRAFT)
    client.force_login(pc_member)
    resp = client.post(
        reverse("program_admin_special_event_registration", args=[e.slug]),
        {"action": "open"}, follow=True,
    )
    e.refresh_from_db()
    assert e.status == Event.Status.DRAFT
    assert "still to be announced" in resp.content.decode()
