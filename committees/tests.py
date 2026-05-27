"""Tests for the committees app (USR-7)."""

from __future__ import annotations

from datetime import date

import pytest
from django.db import IntegrityError, transaction

from accounts.models import User
from committees.models import Committee, CommitteeMembership


@pytest.mark.django_db
def test_three_committees_seeded():
    slugs = set(Committee.objects.values_list("slug", flat=True))
    assert {"board", "programming-committee", "lsp-staff"} <= slugs


@pytest.mark.django_db
def test_membership_str_and_active_flag():
    user = User.objects.create_user(email="m@example.com")
    committee = Committee.objects.get(slug="board")
    m = CommitteeMembership.objects.create(
        user=user,
        committee=committee,
        role_in_committee=CommitteeMembership.Role.CHAIR,
        start_date=date(2026, 1, 1),
    )
    assert m.is_active
    assert "active" in str(m)
    assert "Board" in str(m)


@pytest.mark.django_db
def test_active_members_queryset_excludes_ended():
    committee = Committee.objects.get(slug="programming-committee")
    u_active = User.objects.create_user(email="active@example.com")
    u_past = User.objects.create_user(email="past@example.com")
    CommitteeMembership.objects.create(
        user=u_active, committee=committee, start_date=date(2026, 1, 1)
    )
    CommitteeMembership.objects.create(
        user=u_past,
        committee=committee,
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
    )
    actives = list(committee.active_members())
    assert u_active in [m.user for m in actives]
    assert u_past not in [m.user for m in actives]


@pytest.mark.django_db
def test_one_active_membership_per_user_committee():
    committee = Committee.objects.get(slug="lsp-staff")
    user = User.objects.create_user(email="dup@example.com")
    CommitteeMembership.objects.create(
        user=user, committee=committee, start_date=date(2026, 1, 1)
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        CommitteeMembership.objects.create(
            user=user, committee=committee, start_date=date(2026, 2, 1)
        )


@pytest.mark.django_db
def test_historical_memberships_allowed():
    """Multiple past terms for the same user+committee should be fine."""
    committee = Committee.objects.get(slug="board")
    user = User.objects.create_user(email="history@example.com")
    CommitteeMembership.objects.create(
        user=user,
        committee=committee,
        start_date=date(2020, 1, 1),
        end_date=date(2021, 12, 31),
    )
    CommitteeMembership.objects.create(
        user=user,
        committee=committee,
        start_date=date(2023, 1, 1),
        end_date=date(2024, 12, 31),
    )
    CommitteeMembership.objects.create(
        user=user, committee=committee, start_date=date(2026, 1, 1)
    )
    assert user.committee_memberships.filter(committee=committee).count() == 3
    assert (
        user.committee_memberships.filter(committee=committee, end_date__isnull=True).count()
        == 1
    )
