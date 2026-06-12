"""Tests for the web-developer API (token auth + suggestion triage)."""

from __future__ import annotations

import json

import pytest
from django.urls import reverse

from accounts.models import Profile, User
from core.models import StaffRole
from devapi.models import DevApiToken
from notifications.models import Notification
from suggestions.models import Suggestion

pytestmark = pytest.mark.django_db


def _member(email="m@x.test"):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    return u


def _web_dev(email="dev@x.test"):
    u = _member(email)
    StaffRole.objects.get(key=StaffRole.WEB_DEVELOPER).holders.add(u)
    return u


def _token_for(user, label="test"):
    _obj, raw = DevApiToken.issue(user, label)
    return raw


def _auth(raw):
    return {"HTTP_AUTHORIZATION": f"Bearer {raw}"}


def _suggestion(submitter, **kw):
    defaults = dict(title="Fix the footer", kind=Suggestion.Kind.BUG, body="It's broken")
    defaults.update(kw)
    return Suggestion.objects.create(submitted_by=submitter, **defaults)


# --- authentication / authorization -----------------------------------------


def test_missing_token_is_401(client):
    resp = client.get(reverse("devapi:suggestion_list"))
    assert resp.status_code == 401


def test_unknown_token_is_401(client):
    resp = client.get(reverse("devapi:suggestion_list"), **_auth("lspdev_nope"))
    assert resp.status_code == 401


def test_token_without_staff_role_is_403(client):
    raw = _token_for(_member())
    resp = client.get(reverse("devapi:suggestion_list"), **_auth(raw))
    assert resp.status_code == 403


def test_revoked_token_is_401(client):
    obj, raw = DevApiToken.issue(_web_dev(), "x")
    obj.revoked = True
    obj.save()
    resp = client.get(reverse("devapi:suggestion_list"), **_auth(raw))
    assert resp.status_code == 401


def test_disabled_surface_is_503(client, settings):
    settings.DEVAPI_ENABLED = False
    raw = _token_for(_web_dev())
    resp = client.get(reverse("devapi:suggestion_list"), **_auth(raw))
    assert resp.status_code == 503


def test_authenticate_stamps_last_used(client):
    obj, raw = DevApiToken.issue(_web_dev(), "x")
    assert obj.last_used_at is None
    client.get(reverse("devapi:whoami"), **_auth(raw))
    obj.refresh_from_db()
    assert obj.last_used_at is not None


# --- whoami ------------------------------------------------------------------


def test_whoami_reports_user_and_roles(client):
    raw = _token_for(_web_dev("rico@x.test"), label="rico laptop")
    resp = client.get(reverse("devapi:whoami"), **_auth(raw))
    data = resp.json()
    assert data["user"]["email"] == "rico@x.test"
    assert StaffRole.WEB_DEVELOPER in data["staff_roles"]
    assert data["token_label"] == "rico laptop"


# --- list --------------------------------------------------------------------


def test_list_returns_suggestions(client):
    dev = _web_dev()
    _suggestion(dev, title="A")
    _suggestion(dev, title="B")
    raw = _token_for(dev)
    resp = client.get(reverse("devapi:suggestion_list"), **_auth(raw))
    data = resp.json()
    assert data["count"] == 2
    assert {r["title"] for r in data["results"]} == {"A", "B"}


def test_list_filters_by_status_open(client):
    dev = _web_dev()
    _suggestion(dev, title="open one", status=Suggestion.Status.NEW)
    _suggestion(dev, title="done one", status=Suggestion.Status.DONE)
    raw = _token_for(dev)
    resp = client.get(
        reverse("devapi:suggestion_list"), {"status": "open"}, **_auth(raw)
    )
    titles = [r["title"] for r in resp.json()["results"]]
    assert titles == ["open one"]


def test_list_rejects_bad_status(client):
    raw = _token_for(_web_dev())
    resp = client.get(
        reverse("devapi:suggestion_list"), {"status": "bogus"}, **_auth(raw)
    )
    assert resp.status_code == 400


# --- detail ------------------------------------------------------------------


def test_detail_resolves_route(client):
    dev = _web_dev()
    s = _suggestion(dev, page_url="/directory/")
    raw = _token_for(dev)
    resp = client.get(
        reverse("devapi:suggestion_detail", args=[s.pk]), **_auth(raw)
    )
    data = resp.json()
    assert data["id"] == s.pk
    assert data["route"] is not None
    assert data["route"]["url_name"] == "directory"


def test_detail_404(client):
    raw = _token_for(_web_dev())
    resp = client.get(reverse("devapi:suggestion_detail", args=[9999]), **_auth(raw))
    assert resp.status_code == 404


# --- update (triage) ---------------------------------------------------------


def test_update_changes_status_and_stamps_reviewer(client):
    dev = _web_dev()
    submitter = _member("sub@x.test")
    s = _suggestion(submitter, status=Suggestion.Status.NEW)
    raw = _token_for(dev)
    resp = client.post(
        reverse("devapi:suggestion_detail", args=[s.pk]),
        data=json.dumps({"status": "done", "priority": "high", "staff_notes": "shipped"}),
        content_type="application/json",
        **_auth(raw),
    )
    assert resp.status_code == 200
    s.refresh_from_db()
    assert s.status == Suggestion.Status.DONE
    assert s.priority == Suggestion.Priority.HIGH
    assert s.staff_notes == "shipped"
    assert s.reviewed_by_id == dev.id
    assert s.reviewed_at is not None


def test_update_status_notifies_submitter(client):
    dev = _web_dev()
    submitter = _member("sub@x.test")
    s = _suggestion(submitter, status=Suggestion.Status.NEW)
    raw = _token_for(dev)
    client.post(
        reverse("devapi:suggestion_detail", args=[s.pk]),
        data=json.dumps({"status": "in_progress"}),
        content_type="application/json",
        **_auth(raw),
    )
    assert Notification.objects.filter(recipient=submitter).exists()


def test_update_rejects_bad_status(client):
    dev = _web_dev()
    s = _suggestion(dev)
    raw = _token_for(dev)
    resp = client.post(
        reverse("devapi:suggestion_detail", args=[s.pk]),
        data=json.dumps({"status": "bogus"}),
        content_type="application/json",
        **_auth(raw),
    )
    assert resp.status_code == 400


def test_update_with_no_fields_is_400(client):
    dev = _web_dev()
    s = _suggestion(dev)
    raw = _token_for(dev)
    resp = client.post(
        reverse("devapi:suggestion_detail", args=[s.pk]),
        data=json.dumps({}),
        content_type="application/json",
        **_auth(raw),
    )
    assert resp.status_code == 400


# --- stats -------------------------------------------------------------------


def test_stats_counts(client):
    dev = _web_dev()
    _suggestion(dev, status=Suggestion.Status.NEW)
    _suggestion(dev, status=Suggestion.Status.DONE, kind=Suggestion.Kind.CONTENT)
    raw = _token_for(dev)
    resp = client.get(reverse("devapi:suggestion_stats"), **_auth(raw))
    data = resp.json()
    assert data["total"] == 2
    assert data["open"] == 1
    assert data["by_status"]["new"] == 1


# --- token model -------------------------------------------------------------


def test_issue_returns_unrecoverable_raw_token():
    obj, raw = DevApiToken.issue(_member(), "x")
    assert raw.startswith("lspdev_")
    assert obj.token_hash != raw
    assert DevApiToken.authenticate(raw) is not None
