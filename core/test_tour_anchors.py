"""The data-tour anchors route hints point at. A refactor that drops one
fails here rather than in a training (route-hints spec)."""

from __future__ import annotations

from datetime import date

import pytest
from django.contrib.auth import get_user_model

from events.models import Event
from workgroups.models import WorkgroupMembership


@pytest.fixture
def faculty(db):
    user = get_user_model().objects.create_user(email="anchor@example.com", password="x")
    ev = Event.objects.create(
        title="Anchored", slug="anchored", event_type=Event.Type.SEMINAR,
        start_date=date(2026, 9, 1), end_date=date(2999, 5, 1), published=True,
        status=Event.Status.OPEN,
    )
    ev.ensure_workgroup()
    WorkgroupMembership.objects.create(
        workgroup=ev.workgroup, user=user, role=WorkgroupMembership.Role.FACULTY,
        start_date=date(2026, 9, 1),
    )
    return user, ev


def _get(client, user, url):
    client.force_login(user)
    resp = client.get(url)
    assert resp.status_code == 200, url
    return resp.content.decode()


def test_header_carries_avatar_and_my_lsp_anchors(client, faculty):
    user, _ = faculty
    body = _get(client, user, "/")
    assert 'data-tour="avatar"' in body
    assert 'data-tour="my-lsp-groups"' in body


def test_my_lsp_hub_and_group_cards_carry_anchors(client, faculty):
    user, ev = faculty
    body = _get(client, user, "/formation/?tab=groups")
    assert 'data-tour="my-lsp-groups"' in body
    assert f'data-tour="group-card" data-tour-slug="{ev.workgroup.slug}"' in body


def test_workspace_carries_tab_edit_and_faculty_tool_anchors(client, faculty):
    user, ev = faculty
    wg = ev.workgroup.slug
    body = _get(client, user, f"/groups/{wg}/?tab=roster")
    assert 'data-tour="ws-tab-roster"' in body
    assert 'data-tour="edit-event"' in body
    assert 'data-tour="generate-code"' in body
    assert 'data-tour="joining-instructions"' in body
    assert 'data-tour="registration-status"' in body


def test_edit_page_carries_registration_status_anchor(client, faculty):
    user, ev = faculty
    body = _get(client, user, f"/events/{ev.slug}/edit/")
    assert 'data-tour="registration-status"' in body


def test_meet_tab_carries_system_check_anchor(client, faculty, settings):
    settings.DAILY_ENABLED = True
    settings.DAILY_API_KEY = "k"
    settings.DAILY_DOMAIN = "lsp.daily.co"
    user, ev = faculty
    body = _get(client, user, f"/groups/{ev.workgroup.slug}/?tab=meet")
    assert 'data-tour="meet-system-check"' in body
