"""The change-review dialog, driven the way a browser drives it (task #817).

Every other review test posts ``decision=…`` straight at the edit view, which
skips the one step that broke on prod: the dialog *rendering* the submitted
form as hidden inputs and the browser posting those back. Here the edit page is
fetched, its form parsed, re-submitted with CRLF line endings (what a browser
sends for a <textarea>), and the dialog's own hidden fields posted back.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.urls import reverse

from accounts.models import User
from core.browser_forms import browser_form
from events.models import CEOrganization, Event, EventChangeRequest, Program

pytestmark = pytest.mark.django_db


def _edit_form(html):
    return browser_form(html, field="title")


@pytest.fixture
def program_seminar(db):
    """The prod shape: a script-imported program seminar, no proposal, with
    multi-line LF text (task #812 put these in the loop)."""
    program = Program.objects.create(academic_year="2026-2027", published=True)
    return Event.objects.create(
        title="Clinical Cases", slug="clinical-cases",
        description="First paragraph.\n\nSecond paragraph.",
        readings="Freud (1900).\nLacan (1966).",
        event_type=Event.Type.SEMINAR, program=program,
        start_date=date(2026, 10, 13), end_date=date(2027, 6, 8),
        published=True, status=Event.Status.OPEN,
    )


@pytest.fixture
def faculty(program_seminar):
    user = User.objects.create_user(email="fac@example.com", first_name="F")
    program_seminar.add_faculty(user)
    return user


def _browser_get(client, event):
    response = client.get(reverse("events:edit", args=[event.slug]))
    assert response.status_code == 200
    return _edit_form(response.content.decode())


def test_resaving_unchanged_text_is_not_a_reviewable_change(
    client, program_seminar, faculty,
):
    """CRLF from the browser against LF on the row used to read as a changed
    description and readings, so every save opened the dialog."""
    client.force_login(faculty)
    data = _browser_get(client, program_seminar)
    data["online_venue"] = [Event.OnlineVenue.EXTERNAL]
    data["access_info"] = ["https://zoom.example/j/1"]

    response = client.post(reverse("events:edit", args=[program_seminar.slug]), data)

    assert response.status_code == 302
    program_seminar.refresh_from_db()
    assert program_seminar.online_venue == Event.OnlineVenue.EXTERNAL
    assert program_seminar.access_info == "https://zoom.example/j/1"
    assert not EventChangeRequest.objects.exists()


@pytest.mark.parametrize("decision", ["minor", "review"])
@pytest.mark.parametrize("with_ce_org", [False, True])
def test_the_dialogs_own_repost_saves(
    client, program_seminar, faculty, decision, with_ce_org,
):
    """The dialog re-posted the CE organizations as the string "[]" (or
    "[1]"), which failed validation, so no decision ever saved anything."""
    if with_ce_org:
        org = CEOrganization.objects.create(name="An accreditor")
        program_seminar.ce_organizations.add(org)
    client.force_login(faculty)
    url = reverse("events:edit", args=[program_seminar.slug])
    data = _browser_get(client, program_seminar)
    data["description"] = ["First paragraph, revised.\r\n\r\nSecond paragraph."]
    data["online_venue"] = [Event.OnlineVenue.EXTERNAL]
    data["access_info"] = ["https://zoom.example/j/1"]
    data["requires_faculty_approval"] = ["on"]  # a checkbox must ride along too

    dialog = client.post(url, data)
    assert dialog.status_code == 200
    assert "How substantial is this change?" in dialog.content.decode()

    repost = _edit_form(dialog.content.decode())
    repost["decision"] = [decision]
    response = client.post(url, repost)

    assert response.status_code == 302, (
        response.context and response.context["form"].errors
    )
    program_seminar.refresh_from_db()
    # The venue is not reviewable, so it lands whichever way the content goes.
    assert program_seminar.online_venue == Event.OnlineVenue.EXTERNAL
    assert program_seminar.access_info == "https://zoom.example/j/1"
    assert program_seminar.requires_faculty_approval is True
    request = EventChangeRequest.objects.get()
    assert request.changed_fields == ["description"]
    if decision == "minor":
        assert program_seminar.description.startswith("First paragraph, revised.")
    else:
        assert program_seminar.description.startswith("First paragraph.")
    if with_ce_org:
        assert list(program_seminar.ce_organizations.all()) == [org]


def test_keep_editing_returns_the_typed_edits(client, program_seminar, faculty):
    """"Keep editing" was a link back to the edit page, which dropped every
    edit the dialog was carrying (task #820)."""
    client.force_login(faculty)
    url = reverse("events:edit", args=[program_seminar.slug])
    data = _browser_get(client, program_seminar)
    data["description"] = ["Entirely new text.\r\n\r\nAnd more."]

    dialog = client.post(url, data)
    repost = _edit_form(dialog.content.decode())
    repost["decision"] = ["edit"]
    response = client.post(url, repost)

    assert response.status_code == 200
    html = response.content.decode()
    assert "Entirely new text." in html
    assert "data-unsaved" in html  # the page says it isn't saved yet
    assert not EventChangeRequest.objects.exists()
    program_seminar.refresh_from_db()
    assert program_seminar.description.startswith("First paragraph.")


def _submit_for_review(client, event, description):
    url = reverse("events:edit", args=[event.slug])
    data = _browser_get(client, event)
    data["description"] = [description]
    repost = _edit_form(client.post(url, data).content.decode())
    repost["decision"] = ["review"]
    assert client.post(url, repost).status_code == 302


def test_a_waiting_change_is_named_on_the_edit_page(client, program_seminar, faculty):
    client.force_login(faculty)
    _submit_for_review(client, program_seminar, "A wholly rewritten description.")

    html = client.get(reverse("events:edit", args=[program_seminar.slug])).content.decode()

    assert "Waiting for the Program Committee: a change to the description" in html


def test_the_queue_warns_when_the_live_text_moved_on(client, program_seminar, faculty):
    """Approving writes the proposal over whatever is live, so an edit made
    while it waited would be reverted unseen (task #820)."""
    client.force_login(faculty)
    _submit_for_review(client, program_seminar, "A wholly rewritten description.")
    request = EventChangeRequest.objects.get()
    assert request.stale_labels() == []

    Event.objects.filter(pk=program_seminar.pk).update(
        description="First paragraph.\n\nSecond paragraph, typo fixed."
    )

    assert EventChangeRequest.objects.get().stale_labels() == ["Description"]
    staff = User.objects.create_user(email="pc@example.com", is_staff=True)
    client.force_login(staff)
    html = client.get(reverse("program_admin_changes")).content.decode()
    assert "Since this was submitted, the live description changed." in html
