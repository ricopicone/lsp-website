"""Who may vote and who may stand (task #813; bylaws Art. 3 §1, Art. 12 §2)."""

import datetime

import pytest

from core.models import StaffRole
from elections import eligibility
from elections.models import VoterRollEntry
from elections.tests.factories import make_election, make_member

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("role,votes,stands", [
    ("analyst", True, True), ("scholar", True, True),
    ("candidate", True, True), ("candidate_scholar", True, True),
    ("pre_candidate", True, False), ("pre_candidate_scholar", True, False),
    ("member", True, False), ("external", False, False),
    ("student", False, False), ("prospective_applicant", False, False),
])
def test_roles(role, votes, stands):
    u = make_member(role=role)
    assert eligibility.is_eligible_voter(u) is votes
    assert eligibility.may_stand(u) is stands


@pytest.mark.parametrize("standing", ["on_leave", "resigned", "emeritus", "retired", "removed"])
def test_only_active_standing_votes(standing):
    assert not eligibility.is_eligible_voter(make_member(standing=standing))


def test_persona_inactive_and_deceased_excluded():
    p = make_member()
    p.profile.is_persona = True
    p.profile.save()
    i = make_member()
    i.is_active = False
    i.save()
    d = make_member()
    d.profile.deceased_on = datetime.date(2026, 1, 1)
    d.profile.save()
    for u in (p, i, d):
        u.refresh_from_db()
        assert not eligibility.is_eligible_voter(u)


def test_administrator_may_not_stand():
    u = make_member(role="analyst")
    StaffRole.objects.get(key=StaffRole.ELECTION_ADMINISTRATOR).holders.add(u)
    assert not eligibility.may_stand(u)


def test_computed_roll_applies_overrides():
    e = make_election()
    keep, gone = make_member(), make_member()
    extra = make_member(role="external")
    VoterRollEntry.objects.create(election=e, user=gone, override="remove", reason="unpaid")
    VoterRollEntry.objects.create(election=e, user=extra, override="add", reason="foundation")
    ids = {u.id for u in eligibility.computed_roll(e)}
    assert keep.id in ids and extra.id in ids and gone.id not in ids
    assert eligibility.is_on_roll(e, extra) and not eligibility.is_on_roll(e, gone)


def test_frozen_roll_reads_rows_not_eligibility():
    from django.utils import timezone
    e = make_election(roll_frozen_at=timezone.now())
    on = make_member()
    make_member()  # eligible, but not on the frozen roll
    VoterRollEntry.objects.create(election=e, user=on, on_roll=True)
    assert list(eligibility.roll_users(e)) == [on]
