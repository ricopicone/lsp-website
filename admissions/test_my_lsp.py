"""The My LSP hub — tab availability, the avatar-menu context processor, the
embedded Profile tab, and the legacy redirects."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.urls import reverse

from accounts.models import Profile, User
from formation.tabs import available_tabs

pytestmark = pytest.mark.django_db


def _user(email, role=Profile.Role.MEMBER):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = role
    u.profile.save()
    return u


# ---- available_tabs --------------------------------------------------------

def test_available_tabs_candidate_full_order():
    u = _user("cand@x.test", role=Profile.Role.CANDIDATE)
    keys = [k for k, _ in available_tabs(u)]
    assert keys == [
        "formation", "groups", "events", "works",
        "tuition", "dues", "proposals", "profile",
    ]


def test_available_tabs_external_has_no_member_tabs():
    u = _user("ext@x.test", role=Profile.Role.EXTERNAL)
    keys = [k for k, _ in available_tabs(u)]
    assert keys == ["formation", "groups", "events", "works", "profile"]


def test_available_tabs_suggestions_requires_flag(settings):
    u = _user("an@x.test", role=Profile.Role.ANALYST)
    settings.SUGGESTIONS_ENABLED = True
    assert "suggestions" in [k for k, _ in available_tabs(u)]
    settings.SUGGESTIONS_ENABLED = False
    assert "suggestions" not in [k for k, _ in available_tabs(u)]


def test_available_tabs_anonymous_empty():
    assert available_tabs(AnonymousUser()) == []


# ---- context processor + avatar menu ---------------------------------------

def test_context_processor_exposes_tabs(client):
    client.force_login(_user("cp@x.test", role=Profile.Role.ANALYST))
    resp = client.get(reverse("core:landing"))
    assert "my_lsp_tabs" in resp.context
    keys = [k for k, _ in resp.context["my_lsp_tabs"]]
    assert keys[0] == "formation" and keys[-1] == "profile"


def test_context_processor_empty_for_anonymous(client):
    resp = client.get(reverse("core:landing"))
    assert resp.context["my_lsp_tabs"] == []


def test_avatar_menu_shows_my_lsp(client):
    client.force_login(_user("nav@x.test", role=Profile.Role.ANALYST))
    body = client.get(reverse("core:landing")).content
    assert b">My LSP<" in body
    assert b"?tab=groups" in body and b"?tab=profile" in body


# ---- tab rendering + gating ------------------------------------------------

def test_works_tab_renders(client):
    client.force_login(_user("w@x.test", role=Profile.Role.ANALYST))
    body = client.get(reverse("formation:formation") + "?tab=works").content
    assert b"Add a work" in body


def test_unavailable_tab_falls_back_to_formation(client):
    """A non-member hand-typing ?tab=proposals gets the Formation tab, not a leak."""
    client.force_login(_user("ext2@x.test", role=Profile.Role.EXTERNAL))
    resp = client.get(reverse("formation:formation") + "?tab=proposals")
    assert resp.status_code == 200
    assert b"My Advisor" in resp.content


def test_profile_tab_embeds_editor(client):
    client.force_login(_user("p@x.test", role=Profile.Role.ANALYST))
    body = client.get(reverse("formation:formation") + "?tab=profile").content
    assert b'id="profile-form"' in body          # the editor form
    assert b'id="cropper-modal"' in body         # the headshot cropper
    assert b'name="next"' in body                # posts back to the tab
    assert b"tab=profile" in body


# ---- profile-save redirect logic -------------------------------------------

def test_profile_saved_redirect_honors_next():
    from accounts.views import _profile_saved_redirect

    next_url = reverse("formation:formation") + "?tab=profile"
    req = RequestFactory().post("/accounts/profile/", {"next": next_url})
    url = _profile_saved_redirect(req)
    assert url.startswith(next_url) and "saved=1" in url


def test_profile_saved_redirect_fallback():
    from accounts.views import _profile_saved_redirect

    req = RequestFactory().post("/accounts/profile/")
    assert _profile_saved_redirect(req) == reverse("profile_edit") + "?saved=1#saved"


# ---- legacy redirects ------------------------------------------------------

def test_legacy_list_pages_redirect(client):
    client.force_login(_user("r@x.test", role=Profile.Role.ANALYST))
    for name, tab in (
        ("works:mine", "works"),
        ("my_proposals", "proposals"),
        ("workgroups:mine", "groups"),
        ("suggestions:mine", "suggestions"),
    ):
        resp = client.get(reverse(name))
        assert resp.status_code == 302 and f"tab={tab}" in resp.url
