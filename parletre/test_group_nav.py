"""Group navigation stays inside Parlêtre (tile menu + sibling switcher),
three channels per workgroup (Discuss/Chat/Video), and the 'All LSP' rename."""
from __future__ import annotations

from datetime import date

import pytest
from django.urls import reverse

from accounts.models import Profile, User
from parletre.models import Channel
from workgroups.models import Workgroup, WorkgroupMembership, build_workgroup

pytestmark = pytest.mark.django_db


def _member(email="m@x.test"):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    return u


def _group_with_member(user, slug="cartel-x"):
    wg = build_workgroup(
        Workgroup.Kind.CARTEL, name="Cartel X", slug=slug, description="",
        landing_visibility="members", content_visibility="private",
    )
    WorkgroupMembership.objects.create(
        workgroup=wg, user=user, role=WorkgroupMembership.Role.MEMBER,
        start_date=date(2026, 1, 1),
    )
    return wg


def test_workgroup_gets_three_channels():
    wg = _group_with_member(_member())
    kinds = set(wg.channels.values_list("kind", flat=True))
    assert {"forum", "chat", "video"} <= kinds


def test_group_tile_links_into_parletre_not_workspace(client):
    u = _member()
    wg = _group_with_member(u)
    client.force_login(u)
    resp = client.get(reverse("parletre:index"))
    assert resp.status_code == 200
    forum = wg.channels.get(kind="forum")
    # Menu links to the Parlêtre channel pages (Discuss/Chat/Video) + a workspace link.
    assert reverse("parletre:channel", args=[forum.slug]).encode() in resp.content
    assert b"Discuss" in resp.content
    assert b"Video" in resp.content
    assert b"Workspace" in resp.content


def test_channel_page_has_sibling_switcher(client):
    u = _member()
    wg = _group_with_member(u, slug="cartel-y")
    client.force_login(u)
    forum = wg.channels.get(kind="forum")
    chat = wg.channels.get(kind="chat")
    resp = client.get(reverse("parletre:channel", args=[forum.slug]))
    assert resp.status_code == 200
    assert b"Open workspace" in resp.content
    assert reverse("parletre:channel", args=[chat.slug]).encode() in resp.content


def test_board_channel_has_no_switcher(client):
    u = _member()
    ch = Channel.objects.create(
        name="Board", slug="board-x", kind=Channel.Kind.FORUM, access=Channel.Access.OPEN
    )
    client.force_login(u)
    resp = client.get(reverse("parletre:channel", args=[ch.slug]))
    assert resp.status_code == 200
    assert b"Open workspace" not in resp.content


def test_open_access_relabeled_all_lsp(client):
    u = _member()
    Channel.objects.create(
        name="Commons", slug="commons-x", kind=Channel.Kind.FORUM, access=Channel.Access.OPEN
    )
    client.force_login(u)
    resp = client.get(reverse("parletre:index"))
    assert b"All LSP" in resp.content
    assert b">Open<" not in resp.content  # the old access badge text is gone
