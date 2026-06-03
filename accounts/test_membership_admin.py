"""Tests for Membership administration (Board record-keeping)."""

from __future__ import annotations

import pytest
from django.urls import reverse

from accounts.membership import current_academic_year_start, record_membership_change
from accounts.models import MembershipTenure, Profile, Source, User

pytestmark = pytest.mark.django_db


def _user(email="m@x.test", role=Profile.Role.EXTERNAL):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = role
    u.profile.save()
    return u


def _board_member(email="board@x.test"):
    from datetime import date

    from committees.models import Committee
    u = User.objects.create_user(email=email, password="x")
    Committee.objects.get(slug="board").add_member(u, start_date=date(2026, 1, 1))
    return u


@pytest.mark.django_db
def test_record_change_admit_opens_tenure_and_updates_profile():
    member = _user(role=Profile.Role.EXTERNAL)
    t = record_membership_change(
        member, role=Profile.Role.STUDENT, standing=Profile.Standing.ACTIVE,
        effective_ay=2026, notes="Admitted",
    )
    member.profile.refresh_from_db()
    assert member.profile.role == Profile.Role.STUDENT
    assert member.profile.standing == Profile.Standing.ACTIVE
    assert t.start_ay == 2026 and t.end_ay is None
    assert t.source == Source.STAFF


@pytest.mark.django_db
def test_advance_closes_prior_and_opens_new():
    member = _user(role=Profile.Role.STUDENT)
    record_membership_change(
        member, role=Profile.Role.STUDENT, standing=Profile.Standing.ACTIVE,
        effective_ay=2024,
    )
    record_membership_change(
        member, role=Profile.Role.PRE_CANDIDATE, standing=Profile.Standing.ACTIVE,
        effective_ay=2026,
    )
    tenures = list(MembershipTenure.objects.filter(user=member).order_by("start_ay"))
    assert len(tenures) == 2
    assert tenures[0].role == Profile.Role.STUDENT
    assert tenures[0].end_ay == 2025  # closed the AY before the change
    assert tenures[1].role == Profile.Role.PRE_CANDIDATE
    assert tenures[1].end_ay is None
    member.profile.refresh_from_db()
    assert member.profile.role == Profile.Role.PRE_CANDIDATE


@pytest.mark.django_db
def test_same_year_correction_edits_in_place():
    member = _user(role=Profile.Role.CANDIDATE)
    record_membership_change(
        member, role=Profile.Role.CANDIDATE, standing=Profile.Standing.ACTIVE,
        effective_ay=2026,
    )
    # Correct standing the same year — no new stub tenure.
    record_membership_change(
        member, role=Profile.Role.CANDIDATE, standing=Profile.Standing.ON_LEAVE,
        effective_ay=2026,
    )
    tenures = list(MembershipTenure.objects.filter(user=member))
    assert len(tenures) == 1
    assert tenures[0].standing == Profile.Standing.ON_LEAVE
    member.profile.refresh_from_db()
    assert member.profile.standing == Profile.Standing.ON_LEAVE


@pytest.mark.django_db
def test_audit_stamp_in_notes():
    member = _user()
    actor = _user(email="actor@x.test")
    t = record_membership_change(
        member, role=Profile.Role.STUDENT, standing=Profile.Standing.ACTIVE,
        effective_ay=2026, notes="Board minutes", by=actor,
    )
    assert "actor@x.test" in t.notes and "Board minutes" in t.notes


@pytest.mark.django_db
def test_current_academic_year_start():
    import datetime
    assert current_academic_year_start(datetime.date(2026, 9, 1)) == 2026
    assert current_academic_year_start(datetime.date(2026, 3, 1)) == 2025


# ---- View ----

def test_membership_admin_gated_to_board(client):
    plain = _user(email="plain@x.test", role=Profile.Role.ANALYST)
    client.force_login(plain)
    assert client.get(reverse("board_membership_admin")).status_code == 403


def test_membership_admin_board_can_record(client):
    board = _board_member()
    target = _user(email="target@x.test", role=Profile.Role.EXTERNAL)
    client.force_login(board)
    resp = client.post(reverse("board_membership_admin"), {
        "member": target.pk,
        "role": Profile.Role.STUDENT,
        "standing": Profile.Standing.ACTIVE,
        "effective_ay": 2026,
        "notes": "Admitted by board",
    })
    assert resp.status_code == 302
    target.profile.refresh_from_db()
    assert target.profile.role == Profile.Role.STUDENT
    assert MembershipTenure.objects.filter(user=target, end_ay__isnull=True).exists()


def test_membership_admin_get_renders_member_timeline(client):
    board = _board_member()
    target = _user(email="t2@x.test", role=Profile.Role.CANDIDATE)
    record_membership_change(
        target, role=Profile.Role.CANDIDATE, standing=Profile.Standing.ACTIVE,
        effective_ay=2025, notes="Seed",
    )
    client.force_login(board)
    resp = client.get(reverse("board_membership_admin") + f"?member={target.pk}")
    assert resp.status_code == 200
    assert b"Timeline" in resp.content
    assert b"Record a change" in resp.content
    assert b"AY 2025" in resp.content
