"""Tests for the shared Workgroup layer — visibility, roster, toggles."""

from __future__ import annotations

import datetime

import pytest
from django.core.exceptions import ValidationError

from accounts.models import Profile, User
from cartels.models import Cartel
from committees.models import Committee
from workgroups.models import Visibility, Workgroup, WorkgroupMembership

pytestmark = pytest.mark.django_db


def _user(email, role=Profile.Role.MEMBER, is_staff=False, first="", last=""):
    u = User.objects.create_user(
        email=email, password="x", is_staff=is_staff, first_name=first, last_name=last
    )
    u.profile.role = role
    u.profile.save()
    return u


def _wg(**kwargs):
    kwargs.setdefault("kind", Workgroup.Kind.CARTEL)
    kwargs.setdefault("name", "Test Group")
    return Workgroup.objects.create(**kwargs)


# ---- Roster / is_member ------------------------------------------------

def test_is_member_only_for_active_membership():
    wg = _wg()
    insider = _user("in@x.test")
    outsider = _user("out@x.test")
    WorkgroupMembership.objects.create(
        workgroup=wg, user=insider, start_date=datetime.date(2026, 1, 1)
    )
    assert wg.is_member(insider) is True
    assert wg.is_member(outsider) is False


def test_ended_membership_is_not_current():
    wg = _wg()
    u = _user("u@x.test")
    WorkgroupMembership.objects.create(
        workgroup=wg, user=u,
        start_date=datetime.date(2024, 1, 1), end_date=datetime.date(2025, 1, 1),
    )
    assert wg.is_member(u) is False
    assert wg.active_members().count() == 0


def test_one_active_membership_per_user_group():
    wg = _wg()
    u = _user("u@x.test")
    d1, d2 = datetime.date(2026, 1, 1), datetime.date(2026, 2, 1)
    WorkgroupMembership.objects.create(workgroup=wg, user=u, start_date=d1)
    with pytest.raises(Exception):  # IntegrityError from the partial-unique constraint
        WorkgroupMembership.objects.create(workgroup=wg, user=u, start_date=d2)


# ---- Visibility --------------------------------------------------------

def test_public_landing_visible_to_anonymous():
    wg = _wg(landing_visibility=Visibility.PUBLIC, content_visibility=Visibility.PRIVATE)
    assert wg.landing_visible_to(None) is True
    assert wg.content_visible_to(None) is False


def test_members_visibility_requires_lsp_member():
    wg = _wg(landing_visibility=Visibility.MEMBERS, content_visibility=Visibility.MEMBERS)
    member = _user("m@x.test", role=Profile.Role.ANALYST)
    guest = _user("g@x.test", role=Profile.Role.EXTERNAL)
    assert wg.content_visible_to(member) is True
    assert wg.content_visible_to(guest) is False


def test_private_content_visible_only_to_group_members():
    wg = _wg(landing_visibility=Visibility.MEMBERS, content_visibility=Visibility.PRIVATE)
    member = _user("m@x.test", role=Profile.Role.ANALYST)        # LSP member, not in group
    insider = _user("i@x.test", role=Profile.Role.ANALYST)
    WorkgroupMembership.objects.create(
        workgroup=wg, user=insider, start_date=datetime.date(2026, 1, 1)
    )
    assert wg.landing_visible_to(member) is True       # MEMBERS landing
    assert wg.content_visible_to(member) is False       # PRIVATE content, not in group
    assert wg.content_visible_to(insider) is True


def test_content_not_more_public_than_landing():
    wg = _wg(landing_visibility=Visibility.PRIVATE, content_visibility=Visibility.PUBLIC)
    with pytest.raises(ValidationError) as exc:
        wg.clean()
    assert "content_visibility" in exc.value.error_dict


def test_committee_member_counts_as_lsp_member_for_members_visibility():
    """A committee member with a non-directory role still passes MEMBERS."""
    wg = _wg(landing_visibility=Visibility.MEMBERS, content_visibility=Visibility.MEMBERS)
    staffer = _user("s@x.test", role=Profile.Role.EXTERNAL)
    committee = Committee.objects.create(name="Ethics", slug="ethics")
    committee.add_member(staffer, start_date=datetime.date(2026, 1, 1))
    assert wg.content_visible_to(staffer) is True


# ---- Toggle seed + Cartel helper --------------------------------------

def test_kind_toggle_defaults_seed():
    assert Workgroup.kind_toggle_defaults(Workgroup.Kind.SEMINAR)["has_works"] is False
    assert Workgroup.kind_toggle_defaults(Workgroup.Kind.WORKING_GROUP)["has_decisions"] is True


def test_cartel_create_with_workgroup_applies_seed():
    cartel = Cartel.objects.create_with_workgroup(name="Speech & Writing")
    assert cartel.workgroup.kind == Workgroup.Kind.CARTEL
    assert cartel.workgroup.slug == "speech-writing"
    assert cartel.workgroup.has_works is True
    assert cartel.workgroup.has_tasks is True       # cartel seed
    assert cartel.workgroup.has_minutes is False     # not in cartel seed
    assert str(cartel) == "Speech & Writing"


def test_slug_autopopulated_from_name():
    wg = _wg(name="The Purloined Letter", slug="")
    assert wg.slug == "the-purloined-letter"


# ---- Workspace surface (views) ----------------------------------------

def test_detail_404_when_landing_not_visible(client):
    wg = _wg(landing_visibility=Visibility.PRIVATE, content_visibility=Visibility.PRIVATE)
    # anonymous user: a private-landing group must not even reveal it exists
    resp = client.get(wg.get_absolute_url())
    assert resp.status_code == 404


def test_detail_hides_roster_when_content_private(client):
    wg = _wg(landing_visibility=Visibility.PUBLIC, content_visibility=Visibility.PRIVATE)
    secret = _user("secret@x.test", role=Profile.Role.ANALYST)
    WorkgroupMembership.objects.create(
        workgroup=wg, user=secret, start_date=datetime.date(2026, 1, 1)
    )
    resp = client.get(wg.get_absolute_url())   # anonymous: landing public, content private
    assert resp.status_code == 200
    assert b"private to its members" in resp.content
    assert secret.email.encode() not in resp.content


def test_detail_shows_roster_to_group_member(client):
    wg = _wg(landing_visibility=Visibility.MEMBERS, content_visibility=Visibility.PRIVATE)
    insider = _user("insider@x.test", first="Vera", role=Profile.Role.ANALYST)
    WorkgroupMembership.objects.create(
        workgroup=wg, user=insider, start_date=datetime.date(2026, 1, 1)
    )
    client.force_login(insider)
    resp = client.get(wg.get_absolute_url())
    assert resp.status_code == 200
    assert b"Vera" in resp.content


def test_groups_list_renders_and_groups_by_kind(client):
    Cartel.objects.create_with_workgroup(
        name="Letter Cartel", landing_visibility=Visibility.PUBLIC
    )
    Workgroup.objects.create(
        kind=Workgroup.Kind.WORKING_GROUP, name="Ethics WG",
        landing_visibility=Visibility.PUBLIC,
    )
    resp = client.get("/groups/")
    assert resp.status_code == 200
    assert b"Letter Cartel" in resp.content
    assert b"Ethics WG" in resp.content
    assert b"Working group" in resp.content   # kind grouper header


def test_cartels_index_lists_visible_cartels(client):
    Cartel.objects.create_with_workgroup(
        name="Speech and Writing", landing_visibility=Visibility.PUBLIC
    )
    resp = client.get("/cartels/")
    assert resp.status_code == 200
    assert b"Speech and Writing" in resp.content
