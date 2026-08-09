"""A faculty price change routes through PC review (task #532)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from events.models import (
    Audience,
    Event,
    EventChangeRequest,
    EventProposal,
    PriceTier,
    Program,
)
from events.price_spec import PriceSpec, from_event

pytestmark = pytest.mark.django_db


@pytest.fixture
def approved_event(django_user_model):
    """A published seminar minted from an approved proposal — the only shape
    ``requires_change_review()`` covers."""
    program = Program.objects.create(academic_year="2026-2027", published=True)
    faculty = django_user_model.objects.create_user(
        email="faculty@example.com", password="pw", is_staff=True,
    )
    today = dt.date.today()
    event = Event.objects.create(
        title="Reviewed", slug="reviewed-seminar",
        event_type=Event.Type.SEMINAR, program=program,
        start_date=today, end_date=today + dt.timedelta(days=90),
        published=True, status=Event.Status.OPEN,
    )
    PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("500"),
        minimum_amount=Decimal("0"), covered_by_tuition=True,
    )
    EventProposal.objects.create(
        title="Reviewed", event_type=Event.Type.SEMINAR,
        status=EventProposal.Status.APPROVED, minted_event=event,
        proposed_by=faculty,
    )
    return event, faculty


def test_price_is_a_reviewable_field():
    from events.review import FIELD_LABELS, REVIEWABLE_FIELDS
    assert "price" in REVIEWABLE_FIELDS
    assert FIELD_LABELS["price"] == "Price"


def _request(event, faculty, *, status=EventChangeRequest.Status.PENDING,
             new=Decimal("300"), covers=True, **extra):
    return EventChangeRequest.objects.create(
        event=event, proposed_by=faculty, status=status,
        changed_fields=extra.pop("changed_fields", ["price"]),
        original_price=PriceSpec(
            amount=Decimal("500"), tuition_covers=True).to_dict(),
        proposed_price=PriceSpec(
            amount=new, tuition_covers=covers).to_dict(),
        **extra,
    )


def test_a_pending_price_change_leaves_the_live_price_alone(approved_event):
    event, faculty = approved_event
    request = _request(event, faculty)
    event.refresh_from_db()
    assert from_event(event).amount == Decimal("500")
    assert request.status == EventChangeRequest.Status.PENDING


def test_approving_applies_the_new_price(approved_event):
    event, faculty = approved_event
    request = _request(event, faculty)
    request.approve(faculty)
    event.refresh_from_db()
    assert from_event(event) == PriceSpec(
        amount=Decimal("300"), tuition_covers=True,
    )
    assert request.status == EventChangeRequest.Status.APPROVED


def test_declining_leaves_the_live_price_alone(approved_event):
    event, faculty = approved_event
    request = _request(event, faculty)
    request.decline(faculty, note="Too low.")
    event.refresh_from_db()
    assert from_event(event).amount == Decimal("500")
    assert request.status == EventChangeRequest.Status.DECLINED


def test_field_changes_renders_prices_as_labels(approved_event):
    event, faculty = approved_event
    request = _request(event, faculty, covers=False)
    label_, old, new = request.field_changes()[0]
    assert label_ == "Price"
    assert old == "$500, covered by School tuition"
    assert new == "$300"


def test_a_mixed_change_applies_scalars_and_the_price(approved_event):
    event, faculty = approved_event
    request = _request(
        event, faculty, changed_fields=["title", "price"],
        original_title="Reviewed", proposed_title="Reviewed Again",
    )
    request.approve(faculty)
    event.refresh_from_db()
    assert event.title == "Reviewed Again"
    assert from_event(event).amount == Decimal("300")


def test_a_price_change_never_reprices_an_existing_registration(approved_event):
    """Safety property 2."""
    from django.contrib.auth import get_user_model

    from registrations.models import Registration

    event, faculty = approved_event
    member = get_user_model().objects.create_user(
        email="already@example.com", password="pw",
    )
    registration = Registration.objects.create(
        user=member, event=event, price_tier=event.price_tiers.get(),
        quoted_amount=Decimal("500"), status=Registration.Status.PAID,
    )
    _request(event, faculty).approve(faculty)
    registration.refresh_from_db()
    assert registration.quoted_amount == Decimal("500")


def test_a_price_change_survives_the_confirm_dialog_repost(client, approved_event):
    """The dialog re-posts the form as hidden inputs; the price must ride along."""
    from django.urls import reverse

    event, faculty = approved_event
    client.force_login(faculty)
    url = reverse("events:edit", args=[event.slug])
    payload = {
        "title": event.title, "description": event.description,
        "readings": "", "schedule_note": "", "contact": "", "fee_note": "",
        "fee_type": "fixed", "fee_amount": "300", "tuition_covers": "on",
        "decision": "review",
    }
    response = client.post(url, payload)
    assert response.status_code in (200, 302), getattr(
        response, "context", {}) and response.context["form"].errors
    request = EventChangeRequest.objects.filter(event=event).latest("created_at")
    assert "price" in request.changed_fields
    assert PriceSpec.from_dict(request.proposed_price).amount == Decimal("300")
    event.refresh_from_db()
    assert from_event(event).amount == Decimal("500")  # untouched while pending


def test_an_unchanged_price_is_not_a_reviewable_change(client, approved_event):
    """Re-saving the same price must not manufacture a review request."""
    from django.urls import reverse

    event, faculty = approved_event
    client.force_login(faculty)
    client.post(reverse("events:edit", args=[event.slug]), {
        "title": event.title, "description": event.description,
        "readings": "", "schedule_note": "", "contact": "", "fee_note": "",
        "fee_type": "fixed", "fee_amount": "500", "tuition_covers": "on",
    })
    # Filtered in Python: SQLite (the test DB) has no JSON contains lookup.
    assert not [
        cr for cr in EventChangeRequest.objects.filter(event=event)
        if "price" in cr.changed_fields
    ]
    event.refresh_from_db()
    assert from_event(event).amount == Decimal("500")


def test_the_pc_queue_renders_the_price_diff(client, approved_event):
    """The Changes tab must show Price as labels, not raw dicts."""
    from django.urls import reverse

    event, faculty = approved_event
    _request(event, faculty, covers=False)
    client.force_login(faculty)
    body = client.get(reverse("program_admin_changes")).content.decode()
    assert "Price" in body
    assert "$500, covered by School tuition" in body
    assert "$300" in body
    assert "tuition_covers" not in body  # never the raw dict
