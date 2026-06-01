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
