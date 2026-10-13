"""Every state change in an election (task #813)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from elections import ballots, services
from elections.models import VoterRollEntry
from elections.tests.factories import make_election, make_member, make_nomination

pytestmark = pytest.mark.django_db


# --- nominations ---------------------------------------------------------------

def test_nomination_refused_outside_window():
    with pytest.raises(services.ElectionError):
        services.submit_nomination(make_election("review"), make_member(), "letter")


def test_nomination_refused_for_pre_candidate():
    with pytest.raises(services.ElectionError):
        services.submit_nomination(make_election("nominating"),
                                   make_member(role="pre_candidate"), "letter")


def test_nomination_needs_a_letter():
    with pytest.raises(services.ElectionError):
        services.submit_nomination(make_election("nominating"), make_member(), "   ")


def test_nominate_edit_withdraw_resubmit():
    e = make_election("nominating")
    u = make_member()
    n = services.submit_nomination(e, u, "first")
    services.withdraw_nomination(n)
    n.refresh_from_db()
    assert n.withdrawn_at
    n2 = services.submit_nomination(e, u, "second")
    assert n2.pk == n.pk and n2.withdrawn_at is None and n2.letter == "second"


def test_withdraw_refused_after_close():
    n = make_nomination(make_election("review"), status="pending")
    with pytest.raises(services.ElectionError):
        services.withdraw_nomination(n)


# --- Board review and the slate -----------------------------------------------------

def test_review_only_in_review_phase():
    n = make_nomination(make_election("slate"))
    with pytest.raises(services.ElectionError):
        services.review_nomination(n, make_member(), "declined")


def test_review_records_decision_and_audits():
    e = make_election("review")
    n = make_nomination(e, status="pending")
    director = make_member()
    services.review_nomination(n, director, "declined", "not eligible")
    n.refresh_from_db()
    e.refresh_from_db()
    assert n.status == "declined" and n.reviewed_by == director and n.board_note == "not eligible"
    assert "not accepted" in e.audit_notes


def test_publish_slate_requires_no_pending():
    e = make_election("review")
    make_nomination(e, status="pending")
    with pytest.raises(services.ElectionError):
        services.publish_slate(e, make_member())


def test_publish_slate_ignores_withdrawn_pending():
    e = make_election("review")
    make_nomination(e)
    make_nomination(e, status="pending").__class__.objects.filter(status="pending").update(
        withdrawn_at=timezone.now())
    services.publish_slate(e, make_member())
    e.refresh_from_db()
    assert e.slate_published_at


def test_publish_slate_refuses_after_voting_close():
    now = timezone.now()
    e = make_election("review", voting_open_at=now - timedelta(days=1),
                      voting_close_at=now - timedelta(minutes=1))
    make_nomination(e)
    with pytest.raises(services.ElectionError):
        services.publish_slate(e, make_member())


def test_publish_slate_stamps_audits_and_tells_candidates(mailoutbox, django_capture_on_commit_callbacks):
    e = make_election("review")
    cand = make_nomination(e)
    make_nomination(e, status="declined")
    admin = make_member()
    with django_capture_on_commit_callbacks(execute=True):
        services.publish_slate(e, admin)
    e.refresh_from_db()
    assert e.slate_published_at and e.slate_published_by == admin
    assert "Published the slate" in e.audit_notes
    assert [m.to for m in mailoutbox] == [[cand.user.email]]


def test_acclaim_requires_few_candidates():
    e = make_election("slate", seats=2)
    for _ in range(3):
        make_nomination(e)
    with pytest.raises(services.ElectionError):
        services.acclaim(e, make_member())


def test_acclaim_closes_election():
    e = make_election("slate", seats=2)
    make_nomination(e)
    services.acclaim(e, make_member())
    e.refresh_from_db()
    assert e.phase == "acclaimed"


# --- the roll -----------------------------------------------------------------------

def test_freeze_writes_roll_once():
    e = make_election("voting")
    a, b = make_member(), make_member(role="external")
    services.set_override(e, b, "add", "foundation member", make_member())
    assert services.ensure_roll_frozen(e) is True
    assert services.ensure_roll_frozen(e) is False
    on = set(VoterRollEntry.objects.filter(election=e, on_roll=True)
             .values_list("user_id", flat=True))
    assert {a.id, b.id} <= on


def test_no_freeze_before_voting():
    e = make_election("slate")
    assert services.ensure_roll_frozen(e) is False
    e.refresh_from_db()
    assert e.roll_frozen_at is None


def test_override_needs_reason():
    with pytest.raises(services.ElectionError):
        services.set_override(make_election(), make_member(), "remove", " ", make_member())


def test_post_freeze_add_puts_on_roll():
    e = make_election("voting")
    services.ensure_roll_frozen(e)
    late = make_member(role="external")
    services.set_override(e, late, "add", "missed", make_member())
    assert late.id in services.roll_ids(e)


def test_remove_voter_who_voted_refused():
    e = make_election("voting")
    cand = make_nomination(e)
    v = make_member()
    services.ensure_roll_frozen(e)
    services.cast_ballot(e, v, [cand.id])
    with pytest.raises(services.ElectionError):
        services.set_override(e, v, "remove", "oops", make_member())


# --- voting ---------------------------------------------------------------------------

def test_cast_requires_roll():
    e = make_election("voting")
    cand = make_nomination(e)
    with pytest.raises(services.ElectionError):
        services.cast_ballot(e, make_member(role="external"), [cand.id])


def test_cast_requires_voting_open():
    e = make_election("closed")
    cand = make_nomination(e)
    with pytest.raises(services.ElectionError):
        services.cast_ballot(e, make_member(), [cand.id])


def test_cast_freezes_roll_lazily():
    e = make_election("voting")
    cand = make_nomination(e)
    services.cast_ballot(e, make_member(), [cand.id])
    e.refresh_from_db()
    assert e.roll_frozen_at


def test_ballot_recorded_email_has_no_choices(mailoutbox, django_capture_on_commit_callbacks):
    e = make_election("voting")
    cand = make_nomination(e, user=make_member(first="Zelda", last="Quillfeather"))
    v = make_member()
    with django_capture_on_commit_callbacks(execute=True):
        services.cast_ballot(e, v, [cand.id])
    assert [m.to for m in mailoutbox] == [[v.email]]
    assert "Quillfeather" not in mailoutbox[0].body + mailoutbox[0].subject
    # The link is the member's My LSP hub, not the public About > Formation page.
    assert "/formation/?tab=election" in mailoutbox[0].body
    assert "/about/formation" not in mailoutbox[0].body


def test_remind_nonvoters_only(mailoutbox, django_capture_on_commit_callbacks):
    e = make_election("voting")
    cand = make_nomination(e)
    voted, waiting = make_member(), make_member()
    services.ensure_roll_frozen(e)
    ballots.cast(e, voted, [cand.id])
    with django_capture_on_commit_callbacks(execute=True):
        n = services.remind_nonvoters(e, make_member())
    recipients = {m.to[0] for m in mailoutbox}
    assert n == len(services.roll_ids(e)) - 1
    assert waiting.email in recipients and voted.email not in recipients


# --- dates ------------------------------------------------------------------------------

def test_open_and_close_now():
    e = make_election("draft")
    admin = make_member()
    services.open_now(e, "nominations", admin)
    assert e.phase == "nominating"
    services.close_now(e, "nominations", admin)
    assert e.phase == "review"
    e.refresh_from_db()
    assert "Opened nominations now" in e.audit_notes


def test_close_now_refused_when_not_open():
    with pytest.raises(services.ElectionError):
        services.close_now(make_election("draft"), "voting", make_member())


# --- count and results --------------------------------------------------------------

def test_run_count_and_analyst_check():
    e = make_election("closed", seats=1)
    a = make_nomination(e, user=make_member(role="candidate"))
    services.ensure_roll_frozen(e)
    for _ in range(3):
        ballots.cast(e, make_member(), [a.id])
    result = services.run_count(e, make_member())
    e.refresh_from_db()
    assert e.counted_at and result["elected"] == [a.id]
    assert result["names"][str(a.id)] == a.name
    assert result["analyst_check"]["short"] is True


def test_run_count_refused_while_voting():
    with pytest.raises(services.ElectionError):
        services.run_count(make_election("voting"), make_member())


def test_publish_results_needs_count(mailoutbox, django_capture_on_commit_callbacks):
    e = make_election("closed", seats=1)
    a = make_nomination(e)
    with pytest.raises(services.ElectionError):
        services.publish_results(e, make_member())
    services.ensure_roll_frozen(e)
    ballots.cast(e, make_member(), [a.id])
    services.run_count(e, make_member())
    with django_capture_on_commit_callbacks(execute=True):
        services.publish_results(e, make_member())
    e.refresh_from_db()
    assert e.phase == "published" and mailoutbox


# --- the scheduled job ---------------------------------------------------------------

def test_advance_sends_call_once(mailoutbox, django_capture_on_commit_callbacks):
    voter = make_member()
    e = make_election("nominating")
    with django_capture_on_commit_callbacks(execute=True):
        assert services.advance_elections()["calls"] == 1
        assert services.advance_elections()["calls"] == 0
    e.refresh_from_db()
    assert e.call_sent_at
    assert voter.email in {m.to[0] for m in mailoutbox}


def test_advance_does_nothing_for_draft():
    make_election("draft")
    assert services.advance_elections() == {"calls": 0, "frozen": 0, "voting_notices": 0}


def test_advance_freezes_and_sends_voting_notice_once():
    make_member()
    e = make_election("voting", call_sent_at=timezone.now())
    assert services.advance_elections() == {"calls": 0, "frozen": 1, "voting_notices": 1}
    assert services.advance_elections() == {"calls": 0, "frozen": 0, "voting_notices": 0}
    e.refresh_from_db()
    assert e.roll_frozen_at and e.voting_notice_sent_at
