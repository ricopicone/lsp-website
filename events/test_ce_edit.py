"""Editing CE on the event edit form (task #486)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import User
from events.ce import CECreditBasis
from events.models import CEOrganization, Event, EventChangeRequest


@pytest.fixture
def event(db):
    return Event.objects.create(
        title="Seminar XI", slug="seminar-xi", description="initial body",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
        published=True, status=Event.Status.OPEN,
    )


@pytest.fixture
def faculty(db, event):
    u = User.objects.create_user(email="fac-ce@x.test")
    u.profile.is_faculty = True
    u.profile.save()
    event.add_faculty(u)
    return u


@pytest.fixture
def org(db):
    return CEOrganization.objects.create(name="GPPA")


def _post(event, **overrides):
    data = {
        "title": event.title,
        "description": event.description,
        "readings": "",
        "schedule_note": "",
        "contact": "",
        "fee_note": "",
        "ce_credits_basis": CECreditBasis.TOTAL,
        "ce_note": "",
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
def test_faculty_can_record_ce(client, event, faculty, org):
    client.force_login(faculty)
    response = client.post(reverse("events:edit", args=[event.slug]), _post(
        event, offers_ce="on", ce_credits="2", ce_credits_basis=CECreditBasis.PER_MEETING,
        ce_note="Full attendance required.", ce_organizations=[str(org.pk)],
    ))
    assert response.status_code == 302
    event.refresh_from_db()
    assert event.offers_ce is True
    assert event.ce_credits == Decimal("2")
    assert event.ce_credits_basis == CECreditBasis.PER_MEETING
    assert event.ce_note == "Full attendance required."
    assert list(event.ce_organizations.all()) == [org]


@pytest.mark.django_db
def test_ce_applies_immediately_on_an_approved_event(client, event, faculty, org):
    """CE is a factual accreditation record, not program content the PC vetted,
    so it must not raise the certify-or-submit dialog."""
    from events.models import EventProposal

    proposer = User.objects.create_user(email="prop-ce@x.test")
    EventProposal.objects.create(
        proposed_by=proposer, event_type=Event.Type.SEMINAR, title=event.title,
        description=event.description, start_date=event.start_date,
        end_date=event.end_date, status=EventProposal.Status.APPROVED,
        minted_event=event,
    )
    assert event.requires_change_review()

    client.force_login(faculty)
    response = client.post(reverse("events:edit", args=[event.slug]), _post(
        event, offers_ce="on", ce_credits="6", ce_organizations=[str(org.pk)],
    ))
    assert response.status_code == 302          # straight through, no dialog
    event.refresh_from_db()
    assert event.offers_ce is True
    assert list(event.ce_organizations.all()) == [org]
    assert not EventChangeRequest.objects.exists()


@pytest.mark.django_db
def test_ce_saves_alongside_a_reviewable_change(client, event, faculty, org):
    """The reviewable-change branch applies non-reviewable fields directly, and
    a ManyToMany cannot go through setattr()/update_fields."""
    from events.models import EventProposal

    proposer = User.objects.create_user(email="prop-ce2@x.test")
    EventProposal.objects.create(
        proposed_by=proposer, event_type=Event.Type.SEMINAR, title=event.title,
        description=event.description, start_date=event.start_date,
        end_date=event.end_date, status=EventProposal.Status.APPROVED,
        minted_event=event,
    )
    client.force_login(faculty)
    response = client.post(reverse("events:edit", args=[event.slug]), _post(
        event, description="A wholly rewritten body for the seminar.",
        offers_ce="on", ce_organizations=[str(org.pk)], decision="minor",
    ))
    assert response.status_code == 302
    event.refresh_from_db()
    assert event.offers_ce is True
    assert list(event.ce_organizations.all()) == [org]


@pytest.mark.django_db
def test_edit_page_lists_the_organizations_with_the_current_ones_ticked(
    client, event, faculty, org,
):
    event.offers_ce = True
    event.save()
    event.ce_organizations.add(org)
    client.force_login(faculty)
    body = client.get(reverse("events:edit", args=[event.slug])).content.decode()
    assert f'name="ce_organizations" value="{org.pk}"' in body
    assert "GPPA" in body


@pytest.mark.django_db
def test_edit_affordance_is_labelled_edit_event(client, event, faculty):
    """A seminar's event page redirects to its Workspace, where the masthead
    carries the edit affordance, so follow the redirect rather than asserting
    on an empty 302 body."""
    client.force_login(faculty)
    body = client.get(
        reverse("events:detail", args=[event.slug]), follow=True,
    ).content.decode()
    assert "Edit event" in body
    assert "Edit description" not in body


@pytest.mark.django_db
def test_edit_page_offers_the_add_another_logo_control(client, event, faculty):
    client.force_login(faculty)
    body = client.get(reverse("events:edit", args=[event.slug])).content.decode()
    assert "Add another logo" in body
