"""The per-organization page: manage its logo set, URL, and statement (#486)."""

from __future__ import annotations

import io
from datetime import date

import pytest
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from accounts.models import User
from events.ce_images import MAX_LOGOS
from events.models import CEOrganization, CEOrganizationLogo, Event


def _upload(name="logo.png", size=(400, 200)) -> SimpleUploadedFile:
    buf = io.BytesIO()
    Image.new("RGBA", size, (10, 20, 30, 255)).save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


def _blob() -> ContentFile:
    buf = io.BytesIO()
    Image.new("RGBA", (40, 20), (10, 20, 30, 255)).save(buf, format="WEBP")
    return ContentFile(buf.getvalue())


@pytest.fixture
def event(db):
    return Event.objects.create(
        title="Seminar XI", slug="seminar-xi",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
        published=True, status=Event.Status.OPEN,
    )


@pytest.fixture
def faculty(db, event):
    u = User.objects.create_user(email="fac-orgedit@x.test")
    u.profile.is_faculty = True
    u.profile.save()
    event.add_faculty(u)
    return u


@pytest.fixture
def outsider(db):
    return User.objects.create_user(email="outsider-orgedit@x.test")


@pytest.fixture
def org(db, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    o = CEOrganization.objects.create(name="APA", url="https://www.apa.org/")
    o.add_logos([_blob()])
    return o


def _url(event, org):
    return reverse("events:ce_organization_edit", args=[event.slug, org.pk])


@pytest.mark.django_db
def test_the_page_lists_the_logos_and_omits_a_name_field(client, event, org, faculty):
    """The name is the case-insensitive dedup key and renaming ripples through
    every event, so it stays a Django admin action."""
    client.force_login(faculty)
    body = client.get(_url(event, org)).content.decode()
    assert "APA" in body
    assert 'name="url"' in body
    assert 'name="statement"' in body
    assert 'name="name"' not in body


@pytest.mark.django_db
def test_logos_can_be_added(client, event, org, faculty, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    response = client.post(_url(event, org), {
        "url": org.url, "statement": "", "logo": [_upload("b.png"), _upload("c.png")],
    })
    assert response.status_code == 302
    assert org.logos.count() == 3


@pytest.mark.django_db
def test_the_url_and_statement_can_be_edited(client, event, org, faculty):
    client.force_login(faculty)
    response = client.post(_url(event, org), {
        "url": "https://apa.example/", "statement": "Approved provider.",
    })
    assert response.status_code == 302
    org.refresh_from_db()
    assert org.url == "https://apa.example/"
    assert org.statement == "Approved provider."


@pytest.mark.django_db
def test_a_logo_can_be_removed(client, event, org, faculty, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    org.add_logos([_blob()])
    extra = org.logos.last()
    client.force_login(faculty)
    response = client.post(_url(event, org), {"action": "remove", "logo_id": extra.pk})
    assert response.status_code == 302
    assert org.logos.count() == 1
    assert not CEOrganizationLogo.objects.filter(pk=extra.pk).exists()


@pytest.mark.django_db
def test_the_last_logo_cannot_be_removed(client, event, org, faculty):
    """An organization with no logos renders as a statement with no mark, which
    nobody sets out to create. Replace is add-then-remove."""
    only = org.logos.first()
    client.force_login(faculty)
    response = client.post(
        _url(event, org), {"action": "remove", "logo_id": only.pk}, follow=True,
    )
    assert org.logos.count() == 1
    assert b"add the replacement first" in response.content


@pytest.mark.django_db
def test_the_cap_counts_logos_already_there(client, event, org, faculty, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    org.add_logos([_blob() for _ in range(MAX_LOGOS - 1)])   # now at the cap
    client.force_login(faculty)
    response = client.post(_url(event, org), {
        "url": "", "statement": "", "logo": [_upload("over.png")],
    })
    assert response.status_code == 200
    assert b"at most 10 logos" in response.content
    assert org.logos.count() == MAX_LOGOS


@pytest.mark.django_db
def test_someone_who_cannot_edit_the_event_is_refused(client, event, org, outsider):
    client.force_login(outsider)
    assert client.get(_url(event, org)).status_code == 403
    assert client.post(_url(event, org), {"url": "", "statement": ""}).status_code == 403
