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
