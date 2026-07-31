"""Django messages render once, from the base template (2026-07-31).

Before this, `core/base.html` rendered no messages and 30 page templates each
carried their own loop, so a `messages.success()` from a view whose template
lacked one produced nothing at all.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.urls import reverse
from PIL import Image

from accounts.models import User
from events.models import CEOrganization, Event


class _Msg:
    """Stand-in for django.contrib.messages.storage.base.Message."""

    def __init__(self, text, tags):
        self.text = text
        self.tags = tags

    def __str__(self):
        return self.text


# ---- The partial itself ------------------------------------------------


def test_each_level_maps_to_its_daisyui_class():
    html = render_to_string("core/_messages.html", {"messages": [
        _Msg("bad", "error"),
        _Msg("careful", "warning"),
        _Msg("done", "success"),
        _Msg("fyi", "info"),
    ]})
    assert "alert-error" in html
    assert "alert-warning" in html
    assert "alert-success" in html
    assert "alert-info" in html


def test_extra_tags_do_not_break_the_level_match():
    """`messages.success(request, msg, extra_tags="x")` makes tags "x success";
    an `== 'success'` test would silently miss it and fall through."""
    html = render_to_string("core/_messages.html", {"messages": [
        _Msg("done", "x success"),
    ]})
    assert "alert-success" in html
    assert "alert-info" not in html


def test_nothing_renders_without_messages():
    assert render_to_string("core/_messages.html", {"messages": []}).strip() == ""


# ---- End to end --------------------------------------------------------


def _logo():
    buf = io.BytesIO()
    Image.new("RGBA", (40, 20), (10, 20, 30, 255)).save(buf, format="PNG")
    return SimpleUploadedFile("l.png", buf.getvalue(), content_type="image/png")


@pytest.fixture
def event(db):
    return Event.objects.create(
        title="Seminar XI", slug="seminar-xi",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
        published=True, status=Event.Status.OPEN,
    )


@pytest.fixture
def faculty(db, event):
    u = User.objects.create_user(email="fac-msg@x.test")
    u.profile.is_faculty = True
    u.profile.save()
    event.add_faculty(u)
    return u


@pytest.mark.django_db
def test_a_message_reaches_a_page_that_had_no_loop(
    client, event, faculty, settings, tmp_path,
):
    """events/event_edit.html never rendered messages, so this confirmation was
    invisible before."""
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    response = client.post(
        reverse("events:ce_organization_add", args=[event.slug]),
        {"name": "APA", "logo": [_logo()]},
        follow=True,
    )
    assert b"Added APA and applied it to this event." in response.content


@pytest.mark.django_db
def test_a_message_renders_exactly_once(client, event, faculty, settings, tmp_path):
    """ce_organization_edit.html carried its own loop; with the base rendering
    in place it must not print twice."""
    settings.MEDIA_ROOT = str(tmp_path)
    org = CEOrganization.objects.create(name="GPPA")
    from events.ce_images import normalize_logo
    org.add_logos([normalize_logo(_logo())])
    client.force_login(faculty)
    body = client.post(
        reverse("events:ce_organization_edit", args=[event.slug, org.pk]),
        {"action": "remove", "logo_id": org.logos.first().pk},
        follow=True,
    ).content.decode()
    assert body.count("An organization needs at least one logo.") == 1
