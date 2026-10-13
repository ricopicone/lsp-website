"""The change-review dialog, driven the way a browser drives it (task #817).

Every other review test posts ``decision=…`` straight at the edit view, which
skips the one step that broke on prod: the dialog *rendering* the submitted
form as hidden inputs and the browser posting those back. Here the edit page is
fetched, its form parsed, re-submitted with CRLF line endings (what a browser
sends for a <textarea>), and the dialog's own hidden fields posted back.
"""

from __future__ import annotations

from datetime import date
from html import unescape
from html.parser import HTMLParser

import pytest
from django.urls import reverse

from accounts.models import User
from events.models import CEOrganization, Event, EventChangeRequest, Program

pytestmark = pytest.mark.django_db


class _FormParser(HTMLParser):
    """Collect each <form>'s successful controls the way a browser submits them."""

    def __init__(self):
        super().__init__()
        self.forms, self._form, self._textarea, self._select = [], None, None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self._form = []
            self.forms.append(self._form)
        if self._form is None:
            return
        name = a.get("name")
        if tag == "input" and name:
            kind = a.get("type", "text")
            if kind in ("checkbox", "radio"):
                if "checked" in a:
                    self._form.append((name, a.get("value", "on")))
            elif kind not in ("submit", "button", "file"):
                self._form.append((name, a.get("value", "")))
        elif tag == "textarea":
            self._textarea = [name, ""]
        elif tag == "select":
            self._select = [name, None, None]
        elif tag == "option" and self._select:
            if self._select[2] is None:
                self._select[2] = a.get("value", "")
            if "selected" in a:
                self._select[1] = a.get("value", "")

    def handle_data(self, data):
        if self._textarea:
            self._textarea[1] += data

    def handle_endtag(self, tag):
        if tag == "textarea" and self._textarea:
            name, value = self._textarea
            # A browser drops one newline straight after <textarea>, and
            # submits the content's line breaks as CRLF.
            if value.startswith("\n"):
                value = value[1:]
            value = unescape(value).replace("\r\n", "\n").replace("\n", "\r\n")
            if name:
                self._form.append((name, value))
            self._textarea = None
        elif tag == "select" and self._select:
            name, chosen, first = self._select
            self._form.append((name, chosen if chosen is not None else first))
            self._select = None
        elif tag == "form":
            self._form = None


def _edit_form(html):
    parser = _FormParser()
    parser.feed(html)
    form = next(f for f in parser.forms if any(k == "title" for k, _ in f))
    data = {}
    for key, value in form:
        data.setdefault(key, []).append(unescape(value))
    data.pop("csrfmiddlewaretoken", None)
    return data


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
