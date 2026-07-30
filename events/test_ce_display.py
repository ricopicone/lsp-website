"""CE panel rendering on the event page and the Workspace Overview (task #486)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from accounts.models import User
from events.ce import CECreditBasis
from events.models import CEOrganization, Event


@pytest.fixture
def logo():
    """A 1x1 PNG is enough — these tests care about markup, not pixels."""
    return SimpleUploadedFile(
        "apa.png",
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
        b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82",
        content_type="image/png",
    )


@pytest.fixture
def event(db):
    return Event.objects.create(
        title="Working with Masochism", slug="masochism",
        description="A day on the economy of masochism.",
        start_date=date(2026, 10, 3), end_date=date(2026, 10, 3),
        published=True, status=Event.Status.OPEN,
    )


@pytest.mark.django_db
def test_no_ce_panel_when_ce_is_off(client, event):
    response = client.get(reverse("events:detail", args=[event.slug]))
    assert b"Continuing education" not in response.content


@pytest.mark.django_db
def test_ce_panel_shows_the_credit_line(client, event):
    event.offers_ce = True
    event.ce_credits = Decimal("6.00")
    event.save()
    response = client.get(reverse("events:detail", args=[event.slug]))
    assert b"Continuing education" in response.content
    assert b"Approved for 6 CE credits." in response.content


@pytest.mark.django_db
def test_ce_panel_renders_when_the_event_has_no_description(client, event):
    """About is wrapped in {% if event.description %}; the CE panel must not be
    swallowed by an event whose description is not written yet."""
    event.description = ""
    event.offers_ce = True
    event.save()
    response = client.get(reverse("events:detail", args=[event.slug]))
    assert b"CE credits available." in response.content


@pytest.mark.django_db
def test_ce_panel_shows_logo_statement_and_note(client, event, logo, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    org = CEOrganization.objects.create(
        name="American Psychological Association",
        logo=logo,
        url="https://www.apa.org/",
        statement="LSP maintains responsibility for this program and its content.",
    )
    event.offers_ce = True
    event.ce_credits = Decimal("2.00")
    event.ce_credits_basis = CECreditBasis.PER_MEETING
    event.ce_note = "Full attendance is required for credit."
    event.save()
    event.ce_organizations.add(org)

    body = client.get(reverse("events:detail", args=[event.slug])).content.decode()
    assert "Approved for 2 CE credits per meeting." in body
    assert 'alt="American Psychological Association logo"' in body
    assert "https://www.apa.org/" in body
    assert "LSP maintains responsibility for this program and its content." in body
    assert "Full attendance is required for credit." in body


@pytest.mark.django_db
def test_ce_panel_appears_on_the_workspace_overview(client, event):
    """The Overview tab shares events/_event_summary.html, so it gets the panel
    from the same partial. A Workspace is gated (landing_visible_to), so this
    signs in an LSP member rather than browsing anonymously."""
    from accounts.models import Profile

    member = User.objects.create_user(email="member-ce@x.test")
    member.profile.role = Profile.Role.ANALYST
    member.profile.save()
    client.force_login(member)

    event.event_type = Event.Type.SEMINAR
    event.offers_ce = True
    event.ce_credits = Decimal("2.00")
    event.ce_credits_basis = CECreditBasis.PER_MEETING
    event.save()
    workgroup = event.ensure_workgroup()
    response = client.get(workgroup.get_absolute_url())
    assert b"Approved for 2 CE credits per meeting." in response.content
