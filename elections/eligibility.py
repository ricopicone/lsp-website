"""Who may vote and who may stand (task #813).

Deliberately NOT ``accounts.permissions.lsp_members()``: that answers "may
this person see members-only pages" and admits Django staff, LSP Staff and
committee-serving Auditors. Voting is narrower: the bylaws' member roles in
active standing (Art. 12 §2). "Paid their fees" is applied by the
administrator through roll overrides, not here, because the dues ledger is
still mid-cleanup and an automatic check could disenfranchise someone.
"""

from __future__ import annotations

from accounts.models import Profile, User
from core.access import has_staff_role
from core.models import StaffRole

VOTER_ROLES = frozenset({
    "analyst", "scholar", "candidate", "candidate_scholar",
    "pre_candidate", "pre_candidate_scholar", "member",
})
#: "elected from among its Candidates and Analysts" (Art. 3 §1), read as the
#: senior grades of both tracks.
CANDIDATE_ROLES = frozenset({"analyst", "scholar", "candidate", "candidate_scholar"})

_ORDER = ("last_name", "first_name", "email")


def eligible_voters_qs():
    """Everyone the bylaws make a voter, before the administrator's overrides."""
    return (
        User.objects.filter(
            is_active=True,
            profile__role__in=VOTER_ROLES,
            profile__standing=Profile.Standing.ACTIVE,
            profile__is_persona=False,
            profile__deceased_on__isnull=True,
        )
        .select_related("profile")
        .order_by(*_ORDER)
    )


def is_eligible_voter(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return eligible_voters_qs().filter(pk=user.pk).exists()


def may_stand(user) -> bool:
    """May self-nominate: a voter in a candidate role who isn't the
    Election Administrator."""
    profile = getattr(user, "profile", None)
    return (
        profile is not None
        and profile.role in CANDIDATE_ROLES
        and is_eligible_voter(user)
        and not has_staff_role(user, StaffRole.ELECTION_ADMINISTRATOR)
    )


def _computed_ids(election) -> set[int]:
    from .models import VoterRollEntry

    overrides = dict(
        VoterRollEntry.objects.filter(election=election)
        .exclude(override="")
        .values_list("user_id", "override")
    )
    removed = {u for u, o in overrides.items() if o == VoterRollEntry.Override.REMOVE}
    added = {u for u, o in overrides.items() if o == VoterRollEntry.Override.ADD}
    eligible = set(eligible_voters_qs().values_list("id", flat=True))
    return (eligible - removed) | added


def computed_roll(election) -> list:
    """Eligible voters plus the administrator's adds, minus removes: the roll
    as it stands before the freeze."""
    return list(
        User.objects.filter(id__in=_computed_ids(election))
        .select_related("profile").order_by(*_ORDER)
    )


def roll_users(election):
    """The voter roll: the frozen rows once frozen, else the computed roll."""
    if election.roll_frozen_at:
        qs = User.objects.filter(
            election_roll_entries__election=election,
            election_roll_entries__on_roll=True,
        )
    else:
        qs = User.objects.filter(id__in=_computed_ids(election))
    return qs.select_related("profile").order_by(*_ORDER)


def is_on_roll(election, user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return roll_users(election).filter(pk=user.pk).exists()
