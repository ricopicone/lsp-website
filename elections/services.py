"""Every state change in an election, each audited (task #813).

Views and the scheduled job call these; nothing else writes Election,
Nomination or roll rows. A refusal raises ``ElectionError`` with a message
fit to show the person who tried.
"""

from __future__ import annotations

import secrets

from django.db import transaction
from django.utils import timezone

from . import ballots, counting, eligibility
from . import notifications as notify
from .models import Election, Nomination, VoterRollEntry

P = Election.Phase


class ElectionError(Exception):
    """A refused action; the message is shown to the person who tried."""


def _name(u) -> str:
    return u.get_full_name() or u.email


def _save(election, by, text, *fields) -> None:
    election.append_audit(by, text)
    election.save(update_fields=[*fields, "audit_notes"])


def current_election():
    """The election in progress, else a draft, else the most recent one. An
    election already under way wins over a newer draft (next year's, or a
    by-election being set up), or the draft would hide it."""
    elections = list(Election.objects.defer("audit_notes", "count_result"))
    live = [e for e in elections if e.phase not in Election.FINAL_PHASES]
    under_way = [e for e in live if e.phase != P.DRAFT]
    if under_way:
        return under_way[0]
    if live:
        return live[0]
    return elections[0] if elections else None


def _locked(election):
    """Re-read ``election`` under a row lock. One-shot actions check their
    phase on this copy, so a second submit from a stale page is refused
    rather than repeated. Call inside ``transaction.atomic()``."""
    return Election.objects.select_for_update().get(pk=election.pk)


def _no_contest(election) -> bool:
    accepted = len(ballots.candidates(election))
    return 0 < accepted <= election.seats


def roll_ids(election) -> set[int]:
    return set(eligibility.roll_users(election).values_list("id", flat=True))


# --- nominations ------------------------------------------------------------------

def submit_nomination(election, user, letter) -> Nomination:
    if election.phase != P.NOMINATING:
        raise ElectionError("Nominations are not open.")
    if not eligibility.may_stand(user):
        raise ElectionError(
            "Only analysts, scholars, candidates and candidate scholars may stand."
        )
    letter = (letter or "").strip()
    if not letter:
        raise ElectionError("Please write a motivation letter.")
    nomination, _ = Nomination.objects.update_or_create(
        election=election, user=user,
        defaults={"letter": letter, "withdrawn_at": None,
                  "role_at_submission": user.profile.role},
    )
    notify.nomination_received(user, election)
    return nomination


def withdraw_nomination(nomination) -> None:
    if nomination.election.phase != P.NOMINATING:
        raise ElectionError(
            "Nominations have closed. Write to the Election Administrator to withdraw."
        )
    nomination.withdrawn_at = timezone.now()
    nomination.save(update_fields=["withdrawn_at", "updated_at"])


def review_nomination(nomination, by, status, note: str = "") -> None:
    election = nomination.election
    if not nomination.is_live:
        raise ElectionError("That nomination was withdrawn.")
    if by is not None and by.pk == nomination.user_id:
        raise ElectionError("You can't decide your own nomination; another director will.")
    if election.phase != P.REVIEW:
        raise ElectionError(
            "Nominations can be reviewed after they close and before the slate "
            "is published."
        )
    if status not in (Nomination.Status.ACCEPTED, Nomination.Status.DECLINED):
        raise ElectionError("Choose accept or decline.")
    nomination.status = status
    nomination.board_note = (note or "").strip()
    nomination.reviewed_by = by
    nomination.reviewed_at = timezone.now()
    nomination.save(update_fields=[
        "status", "board_note", "reviewed_by", "reviewed_at", "updated_at",
    ])
    _save(election, by, f"Board marked {nomination.name}'s nomination "
                        f"{nomination.get_status_display().lower()}.")


# --- the slate and acclamation -------------------------------------------------------

def _review_complete(election) -> list:
    """The accepted nominations, once the Board has decided every one."""
    live = election.nominations.filter(withdrawn_at__isnull=True)
    if live.filter(status=Nomination.Status.PENDING).exists():
        raise ElectionError("The Board has not decided every nomination yet.")
    accepted = list(live.filter(status=Nomination.Status.ACCEPTED).select_related("user"))
    if not accepted:
        raise ElectionError("No nominations were accepted.")
    return accepted


def publish_slate(election, by) -> None:
    now = timezone.now()
    with transaction.atomic():
        e = _locked(election)
        if e.phase_at(now) != P.REVIEW:
            raise ElectionError("The slate can be published only during Board review.")
        accepted = _review_complete(e)
        if e.voting_close_at <= now:
            raise ElectionError(
                "The voting close date has passed. Move the voting dates later "
                "in Settings first."
            )
        if len(accepted) <= e.seats and e.voting_open_at <= now:
            # Publishing would open a vote at once, though the bylaws say an
            # uncontested election needs none.
            raise ElectionError(
                "The candidates don't outnumber the seats, so the bylaws call for "
                "no vote, and publishing now would open voting at once. Close the "
                "election without a vote, or move the voting dates later to hold one."
            )
        e.slate_published_at = now
        e.slate_published_by = by
        _save(e, by, f"Published the slate ({len(accepted)} candidates).",
              "slate_published_at", "slate_published_by")
        notify.candidacy_accepted([n.user for n in accepted], e)
    election.refresh_from_db()


def acclaim(election, by) -> None:
    """Close as elected without a vote (bylaws: no election when the
    accepted candidates do not outnumber the seats). Allowed once the Board
    has decided every nomination and before voting opens; from Board review
    it publishes the slate in the same step."""
    now = timezone.now()
    with transaction.atomic():
        e = _locked(election)
        phase = e.phase_at(now)
        if phase not in (P.REVIEW, P.SLATE):
            raise ElectionError(
                "An election can be closed without a vote after the Board has "
                "decided the nominations and before voting opens."
            )
        accepted = _review_complete(e)
        if len(accepted) > e.seats:
            raise ElectionError(
                "There are more candidates than seats, so the bylaws call for a vote."
            )
        fields = ["acclaimed_at", "acclaimed_by"]
        if e.slate_published_at is None:
            e.slate_published_at, e.slate_published_by = now, by
            fields += ["slate_published_at", "slate_published_by"]
        e.acclaimed_at, e.acclaimed_by = now, by
        _save(e, by, "Closed as elected without a vote.", *fields)
        notify.results(list(eligibility.roll_users(e)), e)
    election.refresh_from_db()


# --- the voter roll -------------------------------------------------------------------

def ensure_roll_frozen(election, now=None) -> bool:
    """Write the voter roll once voting has opened. Idempotent; returns True
    only for the call that froze it. Every voting surface calls this, so a
    voter who arrives before the scheduled job has run still finds a roll."""
    now = now or timezone.now()
    if election.roll_frozen_at:
        return False
    with transaction.atomic():
        e = Election.objects.select_for_update().get(pk=election.pk)
        if e.roll_frozen_at or e.phase_at(now) not in (P.VOTING, P.CLOSED):
            return False
        for user in eligibility.computed_roll(e):
            VoterRollEntry.objects.update_or_create(
                election=e, user=user,
                defaults={"on_roll": True, "role_at_freeze": user.profile.role},
            )
        e.roll_frozen_at = now
        _save(e, None, "Froze the voter roll.", "roll_frozen_at")
    election.roll_frozen_at = now
    return True


def set_override(election, user, override, reason, by) -> None:
    """The administrator adds someone to, or removes someone from, the roll,
    with a reason kept in the record."""
    reason = (reason or "").strip()
    if not reason:
        raise ElectionError("Give a reason; it is kept in the record.")
    if override not in (VoterRollEntry.Override.ADD, VoterRollEntry.Override.REMOVE):
        raise ElectionError("Choose add or remove.")
    with transaction.atomic():
        # Under the same lock the freeze takes, and reading the fresh row: an
        # override from a page loaded before the freeze must still reach the
        # frozen roll, not only the pre-freeze computation.
        e = _locked(election)
        if e.phase in (P.CLOSED, P.COUNTED, P.PUBLISHED, P.ACCLAIMED):
            raise ElectionError("The voter roll is closed.")
        if (override == VoterRollEntry.Override.REMOVE
                and user.id in ballots.voted_user_ids(e)):
            raise ElectionError(f"{_name(user)} has already voted; their ballot stands.")
        row, _ = VoterRollEntry.objects.get_or_create(election=e, user=user)
        row.override = override
        row.reason = reason
        row.override_by = by
        row.override_at = timezone.now()
        if e.roll_frozen_at:
            row.on_roll = override == VoterRollEntry.Override.ADD
            if row.on_roll and not row.role_at_freeze:
                row.role_at_freeze = user.profile.role
        row.save()
        if override == VoterRollEntry.Override.ADD:
            _save(e, by, f"Added {_name(user)} to the roll: {reason}")
        else:
            _save(e, by, f"Removed {_name(user)} from the roll: {reason}")
    election.refresh_from_db()


# --- voting -------------------------------------------------------------------------------

def cast_ballot(election, voter, ranked) -> None:
    if election.phase != P.VOTING:
        raise ElectionError("Voting is not open.")
    ensure_roll_frozen(election)
    if not eligibility.is_on_roll(election, voter):
        raise ElectionError(
            "You are not on this election's voter roll. If that is a mistake, "
            "write to the Election Administrator."
        )
    try:
        ballots.cast(election, voter, ranked)
    except ValueError as exc:
        raise ElectionError(str(exc)) from exc
    notify.ballot_recorded(voter, election)


def remind_nonvoters(election, by) -> int:
    if election.phase != P.VOTING:
        raise ElectionError("Voting is not open.")
    ensure_roll_frozen(election)
    voted = ballots.voted_user_ids(election)
    waiting = [u for u in eligibility.roll_users(election) if u.id not in voted]
    sent = notify.reminder(waiting, election)
    _save(election, by, f"Sent a reminder to {sent} voters who had not voted.")
    return sent


# --- windows ---------------------------------------------------------------------------

_WINDOWS = {
    "nominations": ("nominations_open_at", "nominations_close_at"),
    "voting": ("voting_open_at", "voting_close_at"),
}


def open_now(election, which, by) -> None:
    start, _end = _WINDOWS[which]
    now = timezone.now()
    if getattr(election, start) <= now:
        raise ElectionError(f"{which.capitalize()} have already opened.")
    if which == "voting" and election.nominations_close_at > now:
        raise ElectionError("Close nominations first.")
    setattr(election, start, now)
    _save(election, by, f"Opened {which} now.", start)


def close_now(election, which, by) -> None:
    start, end = _WINDOWS[which]
    now = timezone.now()
    # The phase, not the dates: voting whose date has come is still not open
    # until the slate is published, and closing it then would strand the
    # election in Board review.
    open_phase = P.NOMINATING if which == "nominations" else P.VOTING
    if election.phase_at(now) != open_phase:
        raise ElectionError(f"{which.capitalize()} are not open.")
    setattr(election, end, now)
    _save(election, by, f"Closed {which} now.", end)


# --- the count and results ------------------------------------------------------------

def analyst_check(election, elected_ids) -> dict:
    """The bylaws want at least three analysts on the Board. Counts elected
    analysts plus serving directors whose recorded term outlasts this year.
    A director with no recorded term end is not counted, so the check can
    over-warn but never under-warn. It only warns; humans decide."""
    from committees.models import Committee
    from workgroups.models import WorkgroupMembership

    elected = list(Nomination.objects.filter(id__in=elected_ids))
    elected_analysts = sum(1 for n in elected if n.role_at_submission == "analyst")
    year_end = timezone.localdate().replace(month=12, day=31)
    board = Committee.objects.filter(slug="board").first()
    continuing = 0
    if board is not None and board.workgroup_id:
        continuing = (
            WorkgroupMembership.objects.serving()
            .filter(workgroup_id=board.workgroup_id, end_date__gt=year_end,
                    user__profile__role="analyst")
            .exclude(user_id__in=[n.user_id for n in elected])
            .values("user_id").distinct().count()
        )
    total = elected_analysts + continuing
    return {"elected_analysts": elected_analysts, "continuing_analysts": continuing,
            "total": total, "short": total < 3}


def run_count(election, by) -> dict:
    with transaction.atomic():
        e = _locked(election)
        if e.phase != P.CLOSED:
            raise ElectionError("The count runs once, after voting closes.")
        slate = ballots.candidates(e)
        seed = secrets.randbits(32)
        result = counting.count(
            e.count_method, ballots.anonymous_ballots(e),
            [n.id for n in slate], e.seats, seed,
        )
        result["names"] = {str(n.id): n.name for n in slate}
        result["analyst_check"] = analyst_check(e, result["elected"])
        e.count_result = result
        e.counted_at = timezone.now()
        e.counted_by = by
        note = f"Ran the count ({e.get_count_method_display()})."
        if not result["valid_ballots"]:
            note += " No ballots were cast, so nobody is elected."
        if result["lots"]:
            note += f" A tie was decided by lot (seed {seed})."
        _save(e, by, note, "count_result", "counted_at", "counted_by")
    election.refresh_from_db()
    return result


def publish_results(election, by) -> None:
    with transaction.atomic():
        e = _locked(election)
        if e.phase != P.COUNTED:
            raise ElectionError("Run the count first.")
        e.results_published_at = timezone.now()
        e.results_published_by = by
        _save(e, by, "Published the results.",
              "results_published_at", "results_published_by")
        notify.results(list(eligibility.roll_users(e)), e)
    election.refresh_from_db()


# --- the scheduled job ------------------------------------------------------------------

def advance_elections(now=None) -> dict:
    """Send what a passed date calls for: the call for nominations once they
    open, and at the voting open the roll freeze and the voting notice. Each
    is stamped under a row lock before its mail is queued, so overlapping
    runs send once. Rides the five-minute send_meeting_reminders timer."""
    now = now or timezone.now()
    stats = {"calls": 0, "frozen": 0, "voting_notices": 0}
    for e in Election.objects.filter(acclaimed_at__isnull=True,
                                     results_published_at__isnull=True,
                                     counted_at__isnull=True):
        phase = e.phase_at(now)
        if e.call_sent_at is None and phase != P.DRAFT:
            with transaction.atomic():
                locked = Election.objects.select_for_update().get(pk=e.pk)
                if locked.call_sent_at is None:
                    locked.call_sent_at = now
                    if phase == P.NOMINATING:
                        _save(locked, None, "Sent the call for nominations.",
                              "call_sent_at")
                        notify.call(list(eligibility.eligible_voters_qs()), locked)
                        stats["calls"] += 1
                    else:
                        # The job was down for the whole window: a call
                        # inviting nominations that have closed would mislead.
                        _save(locked, None, "Call for nominations not sent: "
                              "nominations had already closed when the job ran.",
                              "call_sent_at")
        if phase == P.VOTING:
            if ensure_roll_frozen(e, now):
                stats["frozen"] += 1
            with transaction.atomic():
                locked = Election.objects.select_for_update().get(pk=e.pk)
                if locked.voting_notice_sent_at is None:
                    locked.voting_notice_sent_at = now
                    _save(locked, None, "Sent the voting-open notice.",
                          "voting_notice_sent_at")
                    notify.voting_open(list(eligibility.roll_users(locked)), locked)
                    stats["voting_notices"] += 1
    return stats
