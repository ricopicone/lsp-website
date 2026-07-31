"""CE panel rendering on the event page and the Workspace Overview (task #486)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import User
from events.ce import CECreditBasis
from events.models import CEOrganization, Event


def _blob():
    """A WebP blob shaped like normalize_logo() output."""
    import io

    from django.core.files.base import ContentFile
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGBA", (40, 20), (10, 20, 30, 255)).save(buf, format="WEBP")
    return ContentFile(buf.getvalue())


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
def test_ce_panel_shows_logo_statement_and_note(client, event, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    org = CEOrganization.objects.create(
        name="American Psychological Association",
        url="https://www.apa.org/",
        statement="LSP maintains responsibility for this program and its content.",
    )
    org.add_logos([_blob()])
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


@pytest.mark.django_db
def test_every_logo_in_the_set_is_shown(client, event, settings, tmp_path):
    """A body requiring a sponsor mark and a provider seal gets both on every
    event that claims it."""
    settings.MEDIA_ROOT = str(tmp_path)
    org = CEOrganization.objects.create(name="APA")
    org.add_logos([_blob(), _blob(), _blob()])
    event.offers_ce = True
    event.save()
    event.ce_organizations.add(org)

    body = client.get(reverse("events:detail", args=[event.slug])).content.decode()
    assert body.count('alt="APA logo"') == 3


@pytest.mark.django_db
def test_an_organization_with_no_logos_renders_without_error(client, event):
    """Defensive: admin can delete the last row even though the UI refuses to."""
    org = CEOrganization.objects.create(name="Logoless")
    org.statement = "Still has something to say."
    org.save()
    event.offers_ce = True
    event.save()
    event.ce_organizations.add(org)

    response = client.get(reverse("events:detail", args=[event.slug]))
    assert response.status_code == 200
    assert b"Still has something to say." in response.content
