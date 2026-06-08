"""Tests for the member suggestion box."""

from __future__ import annotations

import io

import pytest
from django.core.management import call_command
from django.urls import reverse

from accounts.models import Profile, User
from core.models import StaffRole
from notifications.models import Notification
from suggestions.export import build_brief, resolve_route, write_briefs
from suggestions.models import Suggestion

pytestmark = pytest.mark.django_db


def _member(email="m@x.test"):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    return u


def _web_coordinator(email="web@x.test"):
    u = _member(email)
    StaffRole.objects.get(key=StaffRole.WEB_COORDINATOR).holders.add(u)
    return u


def _tiny_png():
    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (2, 2)).save(buf, "PNG")
    return SimpleUploadedFile("shot.png", buf.getvalue(), content_type="image/png")


# ---- submission -------------------------------------------------------

def test_member_submits_from_page(client, settings):
    settings.SUGGESTIONS_ENABLED = True
    client.force_login(_member())
    resp = client.post(reverse("suggestions:submit"), {
        "kind": "content", "title": "Fix the typo",
        "body": "It says 'teh' on the directory.",
        "page_url": "/directory/", "page_title": "Directory",
    })
    assert resp.status_code == 302
    s = Suggestion.objects.get()
    assert s.title == "Fix the typo"
    assert s.page_url == "/directory/"
    assert s.status == Suggestion.Status.NEW
    assert s.context.get("user_agent") is not None  # server-captured


def test_widget_fetch_returns_json(client, settings):
    settings.SUGGESTIONS_ENABLED = True
    client.force_login(_member())
    resp = client.post(
        reverse("suggestions:submit"),
        {"kind": "bug", "title": "Broken", "body": "404 on save", "page_url": "/x/"},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_body_required(client, settings):
    settings.SUGGESTIONS_ENABLED = True
    client.force_login(_member())
    resp = client.post(
        reverse("suggestions:submit"),
        {"kind": "bug", "title": "No body", "body": "", "page_url": "/x/"},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert resp.status_code == 400
    assert resp.json()["ok"] is False
    assert Suggestion.objects.count() == 0


def test_feature_off_forbids(client, settings):
    settings.SUGGESTIONS_ENABLED = False
    client.force_login(_member())
    assert client.get(reverse("suggestions:suggest")).status_code == 403


def test_submission_notifies_triagers(client, settings):
    settings.SUGGESTIONS_ENABLED = True
    coord = _web_coordinator()
    client.force_login(_member("author@x.test"))
    client.post(reverse("suggestions:submit"), {
        "kind": "feature", "title": "Add a thing", "body": "please", "page_url": "/",
    })
    assert Notification.objects.filter(
        recipient=coord, category="suggestion_filed"
    ).exists()


# ---- privacy ----------------------------------------------------------

def test_mine_shows_only_own(client, settings):
    settings.SUGGESTIONS_ENABLED = True
    a, b = _member("a@x.test"), _member("b@x.test")
    Suggestion.objects.create(submitted_by=a, title="A's", body="x")
    Suggestion.objects.create(submitted_by=b, title="B's", body="y")
    client.force_login(a)
    # /suggestions/mine/ now redirects into the My LSP hub's Suggestions tab.
    resp = client.get(reverse("admissions:formation") + "?tab=suggestions")
    assert b"A&#x27;s" in resp.content or b"A's" in resp.content
    assert b"B's" not in resp.content and b"B&#x27;s" not in resp.content


def test_screenshot_gated_to_owner_and_staff(client, settings):
    settings.SUGGESTIONS_ENABLED = True
    owner = _member("owner@x.test")
    s = Suggestion.objects.create(
        submitted_by=owner, title="shot", body="x", screenshot=_tiny_png()
    )
    try:
        url = reverse("suggestions:screenshot", args=[s.pk])
        client.force_login(_member("intruder@x.test"))
        assert client.get(url).status_code == 404
        client.force_login(owner)
        assert client.get(url).status_code == 200
    finally:
        s.screenshot.delete(save=False)


# ---- triage -----------------------------------------------------------

def test_triage_requires_staff(client, settings):
    settings.SUGGESTIONS_ENABLED = True
    client.force_login(_member())
    assert client.get(reverse("suggestions_triage")).status_code == 403


def test_triage_updates_status_and_notifies_submitter(client, settings):
    settings.SUGGESTIONS_ENABLED = True
    author = _member("author@x.test")
    s = Suggestion.objects.create(submitted_by=author, title="t", body="b")
    coord = _web_coordinator()
    client.force_login(coord)
    resp = client.post(reverse("suggestions_triage"), {
        "pk": s.pk, "status": "acknowledged", "priority": "high",
        "staff_notes": "looking into it",
    })
    assert resp.status_code == 302
    s.refresh_from_db()
    assert s.status == Suggestion.Status.ACKNOWLEDGED
    assert s.priority == Suggestion.Priority.HIGH
    assert s.reviewed_by == coord and s.reviewed_at is not None
    assert Notification.objects.filter(
        recipient=author, category="suggestion_update"
    ).exists()


# ---- export -----------------------------------------------------------

def test_resolve_route_maps_path_to_view():
    route = resolve_route("/directory/")
    assert route is not None
    assert "directory" in route["view"]
    assert route["url_name"] == "directory"


def test_resolve_route_handles_unresolvable():
    assert resolve_route("/no/such/path/ever/") is None
    assert resolve_route("") is None


def test_build_brief_includes_resolved_view():
    s = Suggestion.objects.create(
        submitted_by=_member(), title="Typo", body="fix it", page_url="/directory/",
    )
    brief = build_brief(s)
    assert f"# Suggestion #{s.pk}: Typo" in brief
    assert "## Where" in brief
    assert "directory" in brief  # resolved view path / url name


def test_write_briefs_stamps_exported_at(tmp_path):
    s = Suggestion.objects.create(
        submitted_by=_member(), title="Idea", body="do it", page_url="/directory/",
    )
    written = write_briefs(Suggestion.objects.all(), tmp_path)
    assert len(written) == 1
    assert (tmp_path / f"suggestion-{s.pk}.md").exists()
    assert (tmp_path / "INDEX.md").exists()
    s.refresh_from_db()
    assert s.exported_at is not None


def test_export_command_and_unexported_filter(tmp_path):
    s = Suggestion.objects.create(submitted_by=_member(), title="Cmd", body="x")
    out = tmp_path / "briefs"
    call_command("export_suggestions", out=str(out), stdout=io.StringIO())
    assert (out / f"suggestion-{s.pk}.md").exists()
    s.refresh_from_db()
    assert s.exported_at is not None

    buf = io.StringIO()
    call_command("export_suggestions", "--unexported", out=str(out), stdout=buf)
    assert "No suggestions matched" in buf.getvalue()
