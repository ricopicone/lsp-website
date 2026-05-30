"""Per-field visibility (Public / Members only / Private) — model logic,
editor save, and that the directory + map respect each level by viewer.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import AnonymousUser
from django.urls import reverse

from accounts.models import Profile, User

PUBLIC = Profile.Visibility.PUBLIC
MEMBERS = Profile.Visibility.MEMBERS
PRIVATE = Profile.Visibility.PRIVATE


def _analyst(email="a@x.test"):
    u = User.objects.create_user(email=email, password="x")
    u.first_name, u.last_name = "Ana", "Lyst"
    u.save()
    p = u.profile
    p.role = Profile.Role.ANALYST
    p.save()
    return u


# ---- Model: visible_to -------------------------------------------------


@pytest.mark.django_db
def test_default_visibility_all_public():
    u = _analyst()
    anon = AnonymousUser()
    for key in ("bio", "phone", "email", "location"):
        assert u.profile.visible_to(key, anon) is True


@pytest.mark.django_db
def test_members_only_hidden_from_anon_shown_to_authed():
    u = _analyst()
    u.profile.field_visibility = {"location": MEMBERS}
    u.profile.save()
    other = User.objects.create_user(email="b@x.test", password="x")
    assert u.profile.visible_to("location", AnonymousUser()) is False
    assert u.profile.visible_to("location", other) is True   # any signed-in user
    assert u.profile.visible_to("location", u) is True       # the member themselves


@pytest.mark.django_db
def test_private_only_staff_or_self():
    u = _analyst()
    u.profile.field_visibility = {"phone": PRIVATE}
    u.profile.save()
    member = User.objects.create_user(email="m@x.test", password="x")
    staff = User.objects.create_user(email="s@x.test", password="x")
    staff.is_staff = True
    staff.save()
    assert u.profile.visible_to("phone", AnonymousUser()) is False
    assert u.profile.visible_to("phone", member) is False
    assert u.profile.visible_to("phone", staff) is True
    assert u.profile.visible_to("phone", u) is True  # owner


# ---- Editor saves field_visibility -------------------------------------


@pytest.mark.django_db
def test_editor_saves_visibility_levels(client):
    u = _analyst()
    client.force_login(u)
    resp = client.post(reverse("profile_edit"), {
        "first_name": "Ana", "last_name": "Lyst",
        "vis_bio": PUBLIC, "vis_location": MEMBERS, "vis_phone": PRIVATE,
        # the rest default to public via the form
        "vis_pronouns": PUBLIC, "vis_credentials": PUBLIC,
        "vis_languages_spoken": PUBLIC, "vis_year_joined": PUBLIC,
        "vis_website": PUBLIC, "vis_specialties": PUBLIC, "vis_email": PUBLIC,
    })
    assert resp.status_code == 302
    u.profile.refresh_from_db()
    assert u.profile.visibility_of("location") == MEMBERS
    assert u.profile.visibility_of("phone") == PRIVATE
    assert u.profile.visibility_of("bio") == PUBLIC


# ---- Directory + map respect visibility --------------------------------


@pytest.mark.django_db
def test_directory_detail_respects_levels(client):
    u = _analyst()
    u.profile.location = "Los Gatos, CA"
    u.profile.public_email = "pub@x.test"
    u.profile.public_phone = "+14155550000"
    u.profile.field_visibility = {"location": MEMBERS, "email": PRIVATE, "phone": PUBLIC}
    u.profile.save()
    url = reverse("directory_detail", args=[u.profile.directory_slug])

    # Anonymous: location (members) and email (private) hidden; phone (public) shown.
    body = client.get(url).content
    assert b"Los Gatos" not in body
    assert b"pub@x.test" not in body
    assert b"4155550000" in body or b"415 555 0000" in body

    # Signed-in member: sees members-only location, still not the private email.
    member = User.objects.create_user(email="member@x.test", password="x")
    client.force_login(member)
    body = client.get(url).content
    assert b"Los Gatos" in body
    assert b"pub@x.test" not in body


@pytest.mark.django_db
def test_map_excludes_members_only_location_from_anon(client):
    u = _analyst()
    u.profile.location = "Los Gatos, CA"
    u.profile.location_lat = 37.2
    u.profile.location_lng = -121.9
    u.profile.field_visibility = {"location": MEMBERS}
    u.profile.save()
    data = client.get(reverse("find_an_analyst_pins")).json()
    assert all("Lyst" not in (p.get("name") or "") for p in data["pins"])
