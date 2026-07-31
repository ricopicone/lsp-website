"""Adding an accreditor to the shared library from an event (task #486)."""

from __future__ import annotations

import io
from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from accounts.models import User
from events.models import CEOrganization, Event


def _logo(name="apa.png", size=(400, 200)) -> SimpleUploadedFile:
    img = Image.new("RGBA", size, (10, 20, 30, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


@pytest.fixture
def event(db):
    return Event.objects.create(
        title="Seminar XI", slug="seminar-xi",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
        published=True, status=Event.Status.OPEN,
    )


@pytest.fixture
def faculty(db, event):
    u = User.objects.create_user(email="fac-org@x.test")
    u.profile.is_faculty = True
    u.profile.save()
    event.add_faculty(u)
    return u


@pytest.fixture
def outsider(db):
    return User.objects.create_user(email="outsider@x.test")


@pytest.mark.django_db
def test_adding_an_organization_attaches_it_to_this_event(
    client, event, faculty, settings, tmp_path,
):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    response = client.post(
        reverse("events:ce_organization_add", args=[event.slug]),
        {
            "name": "American Psychological Association",
            "url": "https://www.apa.org/",
            "statement": "LSP maintains responsibility for this program.",
            "logo": _logo(),
        },
    )
    assert response.status_code == 302
    org = CEOrganization.objects.get(name="American Psychological Association")
    assert org.added_by == faculty
    assert list(event.ce_organizations.all()) == [org]


@pytest.mark.django_db
def test_the_stored_logo_is_normalized_webp(client, event, faculty, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    client.post(reverse("events:ce_organization_add", args=[event.slug]), {
        "name": "GPPA", "logo": _logo(size=(4000, 1000)),
    })
    org = CEOrganization.objects.get(name="GPPA")
    img = Image.open(org.logos.first().image.path)
    assert img.format == "WEBP"
    assert img.size == (800, 200)


@pytest.mark.django_db
def test_a_duplicate_name_points_at_the_existing_entry(
    client, event, faculty, settings, tmp_path,
):
    settings.MEDIA_ROOT = str(tmp_path)
    CEOrganization.objects.create(name="American Psychological Association")
    client.force_login(faculty)
    response = client.post(
        reverse("events:ce_organization_add", args=[event.slug]),
        {"name": "american psychological association", "logo": _logo()},
    )
    assert response.status_code == 200
    assert b"is already listed" in response.content
    assert CEOrganization.objects.count() == 1


@pytest.mark.django_db
def test_an_unreadable_logo_is_reported(client, event, faculty, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    bad = SimpleUploadedFile("x.png", b"not an image at all", content_type="image/png")
    response = client.post(
        reverse("events:ce_organization_add", args=[event.slug]),
        {"name": "Nope", "logo": bad},
    )
    assert response.status_code == 200
    assert not CEOrganization.objects.filter(name="Nope").exists()


@pytest.mark.django_db
def test_someone_who_cannot_edit_the_event_cannot_seed_the_library(
    client, event, outsider, settings, tmp_path,
):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(outsider)
    response = client.post(
        reverse("events:ce_organization_add", args=[event.slug]),
        {"name": "Sneaky", "logo": _logo()},
    )
    assert response.status_code == 403
    assert not CEOrganization.objects.exists()


@pytest.mark.django_db
def test_several_logos_can_be_uploaded_at_once(client, event, faculty, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    response = client.post(
        reverse("events:ce_organization_add", args=[event.slug]),
        {"name": "APA", "logo": [_logo("a.png"), _logo("b.png", size=(4000, 1000))]},
    )
    assert response.status_code == 302
    org = CEOrganization.objects.get(name="APA")
    assert org.logos.count() == 2
    # Each one went through the same normalization as a single upload.
    second = Image.open(org.logos.all()[1].image.path)
    assert second.format == "WEBP"
    assert second.size == (800, 200)


@pytest.mark.django_db
def test_at_least_one_logo_is_required(client, event, faculty, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    response = client.post(
        reverse("events:ce_organization_add", args=[event.slug]), {"name": "Naked"},
    )
    assert response.status_code == 200
    assert not CEOrganization.objects.filter(name="Naked").exists()


@pytest.mark.django_db
def test_more_than_ten_logos_is_refused(client, event, faculty, settings, tmp_path):
    from events.ce_images import MAX_LOGOS

    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    response = client.post(
        reverse("events:ce_organization_add", args=[event.slug]),
        {"name": "Greedy", "logo": [_logo(f"{i}.png") for i in range(MAX_LOGOS + 1)]},
    )
    assert response.status_code == 200
    assert b"at most 10 logos" in response.content
    assert not CEOrganization.objects.filter(name="Greedy").exists()
