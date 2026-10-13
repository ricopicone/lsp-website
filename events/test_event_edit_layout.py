"""The event edit page's layout and its in-page CE organization add (task #817).

One Save for the event's details, at the foot of that form; everything that
saves on its own sits below it; adding an accreditor happens in a dialog that
posts by fetch, so unsaved edits to the details survive it.
"""

from __future__ import annotations

import io
import re
from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from accounts.models import User
from events.models import CEOrganization, Event

pytestmark = pytest.mark.django_db


def _logo(name="apa.png"):
    buf = io.BytesIO()
    Image.new("RGBA", (400, 200), (10, 20, 30, 255)).save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


@pytest.fixture
def event(db):
    return Event.objects.create(
        title="Seminar XI", slug="seminar-xi",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
        published=True, status=Event.Status.OPEN,
    )


@pytest.fixture
def faculty(event):
    u = User.objects.create_user(email="fac@x.test")
    event.add_faculty(u)
    return u


def _page(client, event):
    return client.get(reverse("events:edit", args=[event.slug])).content.decode()


def _main_form(html):
    match = re.search(r'<form[^>]*id="event-details-form".*?</form>', html, re.S)
    assert match, "the details form is missing"
    return match.group(0)


def test_the_details_form_has_one_save_and_the_add_form_is_a_dialog(
    client, event, faculty,
):
    client.force_login(faculty)
    html = _page(client, event)
    main = _main_form(html)
    assert len(re.findall(r'<button[^>]*type="submit"', main)) == 1
    assert "Saved separately" in html
    assert "Schedule note" in main
    dialog = re.search(r'<dialog[^>]*id="ce-org-dialog".*?</dialog>', html, re.S)
    assert dialog and reverse("events:ce_organization_add", args=[event.slug]) in dialog.group(0)
    assert "event-edit.js" in html


def test_adding_by_fetch_answers_json_and_applies_the_org(
    client, event, faculty, settings, tmp_path,
):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    response = client.post(
        reverse("events:ce_organization_add", args=[event.slug]),
        {"name": "American Psychological Association", "logo": _logo()},
        HTTP_ACCEPT="application/json",
    )
    assert response.status_code == 200
    data = response.json()
    org = CEOrganization.objects.get(name="American Psychological Association")
    assert data["pk"] == org.pk and data["name"] == org.name
    assert len(data["logos"]) == 1
    assert data["manage_url"] == reverse(
        "events:ce_organization_edit", args=[event.slug, org.pk]
    )
    assert list(event.ce_organizations.all()) == [org]


def test_a_refused_add_by_fetch_answers_the_errors(
    client, event, faculty, settings, tmp_path,
):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    response = client.post(
        reverse("events:ce_organization_add", args=[event.slug]),
        {"name": "Naked"}, HTTP_ACCEPT="application/json",
    )
    assert response.status_code == 400
    assert "logos" in response.json()["errors"]
    assert not CEOrganization.objects.filter(name="Naked").exists()


def test_a_refused_add_without_javascript_reopens_the_dialog(
    client, event, faculty, settings, tmp_path,
):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    html = client.post(
        reverse("events:ce_organization_add", args=[event.slug]), {"name": "Naked"},
    ).content.decode()
    assert re.search(r'<dialog[^>]*id="ce-org-dialog"[^>]*\sopen', html)
