"""Tests for working groups — the thin attach + per-kind config."""

from __future__ import annotations

import pytest

from workgroups.models import Visibility, Workgroup
from workinggroups.models import WorkingGroup

pytestmark = pytest.mark.django_db


def test_create_with_workgroup_applies_working_group_seed():
    wg = WorkingGroup.objects.create_with_workgroup(name="Ethics Working Group")
    g = wg.workgroup
    assert g.kind == Workgroup.Kind.WORKING_GROUP
    assert g.slug == "ethics-working-group"
    # Worksheet defaults: Open landing (members), private contents.
    assert g.landing_visibility == Visibility.MEMBERS
    assert g.content_visibility == Visibility.PRIVATE
    # WORKING_GROUP capability seed: the full suite.
    assert g.has_works and g.has_minutes and g.has_decisions and g.has_tasks
    assert str(wg) == "Ethics Working Group"


def test_working_group_listed_on_groups_index(client):
    WorkingGroup.objects.create_with_workgroup(
        name="Translation Working Group", landing_visibility=Visibility.PUBLIC
    )
    resp = client.get("/groups/working-groups/")
    assert resp.status_code == 200
    assert b"Translation Working Group" in resp.content


def test_working_group_gets_its_own_channel():
    """The auto-provision signal fires for working groups too."""
    wg = WorkingGroup.objects.create_with_workgroup(name="Archive Working Group")
    ch = wg.workgroup.channels.first()
    assert ch is not None
    assert ch.category.name == "Working Groups"


# ---- Board-gated creation (G3) ----------------------------------------

from accounts.models import Profile, User  # noqa: E402
from workgroups.models import WorkgroupMembership  # noqa: E402


def _member(email):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    return u


def _board_member(email="board@x.test"):
    from committees.models import Committee

    u = _member(email)
    Committee.objects.get(slug="board").add_member(u)
    return u


def test_create_with_chair_seeds_chair_and_members_standing():
    chair = _member("chair@x.test")
    m1 = _member("m1@x.test")
    wg = WorkingGroup.objects.create_with_chair(
        name="Ethics WG", description="Aim.", chair=chair, members=[m1, chair],
    )
    g = wg.workgroup
    assert g.kind == Workgroup.Kind.WORKING_GROUP
    assert g.end_date is None   # standing
    assert g.memberships.get(user=chair, end_date__isnull=True).role == \
        WorkgroupMembership.Role.CHAIR
    # chair isn't double-added as a plain member; m1 is a member
    assert g.memberships.filter(user=chair, end_date__isnull=True).count() == 1
    assert g.memberships.get(user=m1, end_date__isnull=True).role == \
        WorkgroupMembership.Role.MEMBER


def test_create_with_chair_dedupes_slug():
    chair = _member("chair@x.test")
    a = WorkingGroup.objects.create_with_chair(name="Same Name", chair=chair)
    b = WorkingGroup.objects.create_with_chair(name="Same Name", chair=chair)
    assert a.workgroup.slug != b.workgroup.slug
    assert b.workgroup.slug.startswith("same-name")


def test_create_view_gated_to_board_and_staff(client):
    # a plain LSP member cannot reach it
    client.force_login(_member("plain@x.test"))
    assert client.get("/working-groups/new/").status_code == 404
    # a Board member can
    client.force_login(_board_member())
    assert client.get("/working-groups/new/").status_code == 200


def test_create_view_creates_working_group(client):
    board = _board_member()
    chair = _member("chair@x.test")
    client.force_login(board)
    resp = client.post("/working-groups/new/", {
        "name": "Translation WG",
        "description": "Translating the Écrits.",
        "chair": "chair@x.test",
        "members": "",
    })
    assert resp.status_code == 302
    wg = WorkingGroup.objects.get(workgroup__name="Translation WG")
    assert wg.workgroup.is_member(chair)
    assert wg.workgroup.memberships.get(user=chair).role == WorkgroupMembership.Role.CHAIR


def test_create_button_shown_only_to_board(client):
    WorkingGroup.objects.create_with_workgroup(
        name="Existing WG", landing_visibility=Visibility.PUBLIC
    )
    client.force_login(_member("plain@x.test"))
    assert b"New working group" not in client.get("/groups/working-groups/").content
    client.force_login(_board_member())
    assert b"New working group" in client.get("/groups/working-groups/").content
