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
def test_the_panel_names_the_accrediting_organization(client, event, settings, tmp_path):
    """The logos alone said nothing about who accredited the event (task #506)."""
    settings.MEDIA_ROOT = str(tmp_path)
    org = CEOrganization.objects.create(
        name="Greater Pittsburgh Psychological Association",
        url="https://gppa.wildapricot.org/",
    )
    org.add_logos([_blob()])
    event.offers_ce = True
    event.save()
    event.ce_organizations.add(org)

    body = client.get(reverse("events:detail", args=[event.slug])).content.decode()
    # As element text, not merely inside the logo's alt="… logo" — the alt was
    # already there and is not what a reader sees.
    assert ">Greater Pittsburgh Psychological Association</a>" in body


@pytest.mark.django_db
def test_the_name_carries_the_outbound_link(client, event, settings, tmp_path):
    """The link used to wrap the logo, which would collide with click-to-zoom;
    it belongs on the name now (task #506)."""
    settings.MEDIA_ROOT = str(tmp_path)
    org = CEOrganization.objects.create(name="GPPA", url="https://gppa.wildapricot.org/")
    org.add_logos([_blob()])
    event.offers_ce = True
    event.save()
    event.ce_organizations.add(org)

    body = client.get(reverse("events:detail", args=[event.slug])).content.decode()
    assert '<a href="https://gppa.wildapricot.org/" target="_blank" rel="noopener"' in body
    assert ">GPPA</a>" in body


@pytest.mark.django_db
def test_an_organization_without_a_url_renders_its_name_as_plain_text(client, event):
    org = CEOrganization.objects.create(name="Unlinked Accreditor")
    event.offers_ce = True
    event.save()
    event.ce_organizations.add(org)

    body = client.get(reverse("events:detail", args=[event.slug])).content.decode()
    assert "Unlinked Accreditor" in body
    assert 'href=""' not in body


@pytest.mark.django_db
def test_each_statement_sits_inside_its_own_organizations_group(client, event, settings, tmp_path):
    """Two accreditors must not have their mandated language pooled at the
    bottom, where either statement reads as applying to both sets of marks."""
    settings.MEDIA_ROOT = str(tmp_path)
    first = CEOrganization.objects.create(name="Alpha Board", statement="Alpha says so.")
    first.add_logos([_blob()])
    second = CEOrganization.objects.create(name="Beta Board", statement="Beta says so.")
    second.add_logos([_blob()])
    event.offers_ce = True
    event.save()
    event.ce_organizations.add(first, second)

    body = client.get(reverse("events:detail", args=[event.slug])).content.decode()
    # Ordering is CEOrganization.Meta.ordering = ("name",), so Alpha precedes Beta.
    assert body.index("Alpha Board") < body.index("Alpha says so.") < body.index("Beta Board")
    assert body.index("Beta Board") < body.index("Beta says so.")


@pytest.mark.django_db
def test_every_logo_is_an_anchor_to_its_own_file(client, event, settings, tmp_path):
    """The no-JS path, and what makes each mark individually zoomable: two marks
    on one accreditor must link to two different files, not one shared modal
    target (task #506)."""
    settings.MEDIA_ROOT = str(tmp_path)
    org = CEOrganization.objects.create(name="Two Marks")
    first, second = org.add_logos([_blob(), _blob()])
    event.offers_ce = True
    event.save()
    event.ce_organizations.add(org)

    body = client.get(reverse("events:detail", args=[event.slug])).content.decode()
    assert f'href="{first.image.url}" ' in body
    assert f'href="{second.image.url}" ' in body
    assert first.image.url != second.image.url
    assert body.count("data-ce-logo ") == 2


@pytest.mark.django_db
def test_the_lightbox_is_rendered_once_for_the_whole_panel(client, event, settings, tmp_path):
    """One dialog, whatever the number of marks — the partial renders at most
    once per page, so a dialog per logo would only duplicate markup and ids."""
    settings.MEDIA_ROOT = str(tmp_path)
    org = CEOrganization.objects.create(name="Three Marks")
    org.add_logos([_blob(), _blob(), _blob()])
    event.offers_ce = True
    event.save()
    event.ce_organizations.add(org)

    body = client.get(reverse("events:detail", args=[event.slug])).content.decode()
    assert body.count('id="ce-logo-modal"') == 1
    assert "lsp-lightbox" in body


@pytest.mark.django_db
def test_no_lightbox_when_the_event_claims_no_organization(client, event):
    """An event marked as offering CE before an accreditor is recorded should
    not carry a dialog with nothing to show."""
    event.offers_ce = True
    event.save()
    body = client.get(reverse("events:detail", args=[event.slug])).content.decode()
    assert "CE credits available." in body
    assert 'id="ce-logo-modal"' not in body


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
