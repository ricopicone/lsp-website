"""Tests for the committees app (USR-7) after the workgroups fold-in.

Committees now attach a ``Workgroup(kind=committee)`` and their roster lives on
``WorkgroupMembership``; LSP Staff is no longer a committee (it became the
``Profile.is_lsp_staff`` designation).
"""

from __future__ import annotations

from datetime import date

import pytest
from django.db import IntegrityError, transaction

from accounts.models import User
from committees.models import Committee
from workgroups.models import Workgroup, WorkgroupMembership


@pytest.mark.django_db
def test_committees_seeded_and_lsp_staff_folded_out():
    slugs = set(Committee.objects.values_list("slug", flat=True))
    assert {"board", "programming-committee"} <= slugs
    # LSP Staff left the committee model (now the is_lsp_staff designation).
    assert "lsp-staff" not in slugs


@pytest.mark.django_db
def test_committee_has_backing_workgroup():
    c = Committee.objects.create(name="Ethics", slug="ethics")
    assert c.workgroup is not None
    assert c.workgroup.kind == Workgroup.Kind.COMMITTEE


@pytest.mark.django_db
def test_every_analyst_is_member_of_meeting_of_analysts():
    from accounts.models import Profile

    c = Committee.objects.get(slug="meeting-of-analysts")
    assert c.workgroup.auto_member_role == Profile.Role.ANALYST

    analyst = User.objects.create_user(email="analyst@x.test")
    analyst.profile.role = Profile.Role.ANALYST
    analyst.profile.save()
    non_analyst = User.objects.create_user(email="scholar@x.test")
    non_analyst.profile.role = Profile.Role.SCHOLAR
    non_analyst.profile.save()

    assert c.workgroup.is_member(analyst) is True
    assert c.workgroup.is_member(non_analyst) is False
    assert analyst in [p.user for p in c.workgroup.participants()]


@pytest.mark.django_db
def test_committee_does_not_derive_from_organized_events():
    """A committee *organizes* events (they link to its workgroup) but does not
    *offer* them. Its roster / membership / Overview must NOT derive from those
    events — otherwise a special-event registrant would become a committee
    "member" and could read its private channel. Regression for the crossed
    wire where the PC Overview showed the Masochism special event.
    """
    from decimal import Decimal

    from events.models import Audience, Event, PriceTier
    from registrations.models import Registration

    pc = Committee.objects.get(slug="programming-committee")
    wg = pc.workgroup

    event = Event.objects.create(
        title="Working with Masochism", slug="masochism",
        event_type="special_event",
        start_date=date(2026, 11, 1), end_date=date(2026, 11, 1),
    )
    event.ensure_workgroup()
    assert event.workgroup_id == wg.id          # links to the PC committee workgroup

    registrant = User.objects.create_user(email="reg@x.test")
    tier = PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("0.00")
    )
    Registration.objects.create(
        user=registrant, event=event, price_tier=tier,
        quoted_amount=Decimal("0.00"), status=Registration.Status.PAID,
    )

    # The leak: the registrant must NOT be a member of the committee workgroup.
    assert wg.is_member(registrant) is False
    # The Overview must not feature the organized event…
    assert wg.primary_event() is None
    # …and the registrant must not appear in the committee roster.
    assert registrant not in [p.user for p in wg.participants()]


@pytest.mark.django_db
def test_add_member_and_active_members_excludes_ended():
    committee = Committee.objects.get(slug="board")
    u_active = User.objects.create_user(email="active@example.com")
    u_past = User.objects.create_user(email="past@example.com")
    committee.add_member(u_active, role=WorkgroupMembership.Role.CHAIR, start_date=date(2026, 1, 1))
    committee.add_member(u_past, start_date=date(2024, 1, 1), end_date=date(2025, 12, 31))
    actives = [m.user for m in committee.active_members()]
    assert u_active in actives
    assert u_past not in actives


@pytest.mark.django_db
def test_active_members_excludes_personas():
    """Training-sandbox personas keep their memberships for impersonation
    fidelity but must never surface on a public roster (the About-page Board
    card reads its roster from ``active_members``). Regression: a seeded
    "Persona Board Chair" leaked onto the public Board of Directors list.
    """
    committee = Committee.objects.get(slug="board")
    real = User.objects.create_user(email="real@example.com")
    persona = User.objects.create_user(email="persona+board-chair@example.com")
    persona.profile.is_persona = True
    persona.profile.save(update_fields=["is_persona"])
    committee.add_member(real, role=WorkgroupMembership.Role.CHAIR)
    committee.add_member(persona, role=WorkgroupMembership.Role.MEMBER)

    roster = [m.user for m in committee.active_members()]
    assert real in roster
    assert persona not in roster


@pytest.mark.django_db
def test_one_active_membership_per_user_committee():
    committee = Committee.objects.get(slug="programming-committee")
    user = User.objects.create_user(email="dup@example.com")
    committee.add_member(user, start_date=date(2026, 1, 1))
    with pytest.raises(IntegrityError), transaction.atomic():
        committee.add_member(user, start_date=date(2026, 2, 1))


@pytest.mark.django_db
def test_historical_memberships_allowed():
    """Multiple past terms for the same user+committee should be fine."""
    committee = Committee.objects.get(slug="board")
    user = User.objects.create_user(email="history@example.com")
    committee.add_member(user, start_date=date(2020, 1, 1), end_date=date(2021, 12, 31))
    committee.add_member(user, start_date=date(2023, 1, 1), end_date=date(2024, 12, 31))
    committee.add_member(user, start_date=date(2026, 1, 1))
    wg = committee.workgroup
    assert WorkgroupMembership.objects.filter(workgroup=wg, user=user).count() == 3
    assert (
        WorkgroupMembership.objects.filter(
            workgroup=wg, user=user, end_date__isnull=True
        ).count()
        == 1
    )


# ---- Phase D (charter editing) + Phase E (MoA schedule split) ----------

from django.urls import reverse  # noqa: E402


def _analyst(email):
    from accounts.models import Profile

    u = User.objects.create_user(email=email, password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    return u


def _on_committee(slug, user, role=WorkgroupMembership.Role.MEMBER):
    Committee.objects.get(slug=slug).add_member(
        user, role=role, start_date=date(2026, 1, 1)
    )


@pytest.mark.django_db
def test_committee_charter_edit_gated_to_manager(client):
    committee = Committee.objects.create(name="Ethics D", slug="ethics-d", public=True)
    wg = committee.workgroup
    chair = _analyst("chair-d@x.test")
    committee.add_member(chair, role=WorkgroupMembership.Role.CHAIR, start_date=date(2026, 1, 1))

    client.force_login(_analyst("plain-d@x.test"))   # not a manager
    assert client.post(f"/committees/{wg.slug}/charter/",
                       {"description": "x", "charter": "y"}).status_code == 404

    client.force_login(chair)
    resp = client.post(f"/committees/{wg.slug}/charter/",
                       {"description": "One-liner", "charter": "Our mandate."})
    assert resp.status_code == 302
    committee.refresh_from_db()
    assert committee.charter == "Our mandate." and committee.description == "One-liner"


@pytest.mark.django_db
def test_committee_charter_form_shown_on_settings_to_manager(client):
    committee = Committee.objects.create(name="Ethics D2", slug="ethics-d2", public=True)
    chair = _analyst("chair-d2@x.test")
    committee.add_member(chair, role=WorkgroupMembership.Role.CHAIR, start_date=date(2026, 1, 1))
    client.force_login(chair)
    resp = client.get(f"{committee.workgroup.get_absolute_url()}?tab=settings")
    assert resp.status_code == 200
    assert b"Charter" in resp.content


@pytest.mark.django_db
def test_board_can_manage_committee_they_are_not_on(client):
    board_member = _analyst("boardie@x.test")
    _on_committee("board", board_member)
    other = Committee.objects.create(name="Outreach", slug="outreach", public=True)
    client.force_login(board_member)
    resp = client.post(f"/committees/{other.workgroup.slug}/charter/",
                       {"description": "Outreach", "charter": "Spread the word."})
    assert resp.status_code == 302
    other.refresh_from_db()
    assert other.charter == "Spread the word."


@pytest.mark.django_db
def test_meeting_of_analysts_schedule_is_chair_managed(client):
    from workgroups.models import WorkgroupMeeting

    wg = Committee.objects.get(slug="meeting-of-analysts").workgroup

    # An analyst is an auto-member: sees the Schedule tab, but can't edit cadence.
    analyst = _analyst("a-moa@x.test")
    client.force_login(analyst)
    resp = client.get(f"{wg.get_absolute_url()}?tab=schedule")
    assert resp.status_code == 200
    assert b"tab=schedule" in resp.content
    assert client.post(reverse("workgroups:meeting_add", args=[wg.slug]),
                       {"starts_at": "2099-01-15T18:00"}).status_code == 404

    # A Board member (manager) can.
    board_member = _analyst("board-moa@x.test")
    _on_committee("board", board_member)
    client.force_login(board_member)
    assert client.post(reverse("workgroups:meeting_add", args=[wg.slug]),
                       {"starts_at": "2099-01-15T18:00"}).status_code == 302
    assert WorkgroupMeeting.objects.filter(workgroup=wg).exists()
