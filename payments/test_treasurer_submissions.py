"""Treasurer approval queue for member history submissions (task #439 §3).

Covers the Reconcile tab's "Member submissions" section and
``treasurer_submission_decide``: approve mints the matching Payment/Charge
per spec (provenance, paid_at/period binding, staff_adjusted); decline just
records a note; both are notified to the member. See
payments/test_ledger_submissions.py for the member-facing create/list half.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import Source, User
from notifications.models import Notification
from payments import ledger
from payments.models import Charge, DuesPeriod, LedgerSubmission, Payment, TuitionPeriod

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_periods():
    TuitionPeriod.objects.all().delete()
    DuesPeriod.objects.all().delete()


@pytest.fixture
def treasurer(client):
    u = User.objects.create_user(email="tr-sub@x.test", password="x", is_staff=True)
    client.force_login(u)
    return u


@pytest.fixture
def member():
    u = User.objects.create_user(email="claimant@x.test", password="x")
    u.profile.role = "candidate"
    u.profile.save()
    return u


def _tuition_period(**overrides):
    kwargs = dict(
        name="AY 2019-2020 T", slug="t-2019-sub",
        start_date=date(2019, 9, 1), end_date=date(2020, 8, 31),
        decision_due_date=date(2019, 8, 31), tuition_amount=Decimal("2000"))
    kwargs.update(overrides)
    return TuitionPeriod.objects.create(**kwargs)


def _dues_period(**overrides):
    kwargs = dict(
        name="AY 2019-2020", slug="ay-2019-sub",
        start_date=date(2019, 9, 1), due_date=date(2019, 9, 30),
        end_date=date(2020, 8, 31),
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"),
        dues_amount_analyst=Decimal("150"))
    kwargs.update(overrides)
    return DuesPeriod.objects.create(**kwargs)


def _submission(user, **overrides):
    kwargs = dict(
        user=user, kind=LedgerSubmission.Kind.PAYMENT,
        category=Payment.Type.TUITION, amount=Decimal("2000.00"),
        claimed_date=date(2019, 9, 15),
        details="I paid $2,000 tuition in fall 2019, by check.",
    )
    kwargs.update(overrides)
    return LedgerSubmission.objects.create(**kwargs)


# --------------------------------------------------------------- approve ---

def test_approve_payment_mints_with_provenance_and_period(client, treasurer, member):
    period = _tuition_period()
    submission = _submission(member)

    resp = client.post(
        reverse("treasurer_submission_decide", args=[submission.id]),
        {"decision": "approve", "note": "Matches the old treasurer's ledger."})
    assert resp.status_code == 302
    submission.refresh_from_db()

    assert submission.status == LedgerSubmission.Status.APPROVED
    assert submission.decided_by == treasurer
    assert submission.decided_at is not None
    assert submission.decision_note == "Matches the old treasurer's ledger."
    assert submission.created_payment is not None
    assert submission.created_charge is None

    payment = submission.created_payment
    assert payment.user == member
    assert payment.payment_type == Payment.Type.TUITION
    assert payment.amount == Decimal("2000.00")
    assert payment.status == Payment.Status.SUCCEEDED
    assert payment.method == Payment.Method.OFFLINE
    assert payment.source == Source.SELF_REPORTED
    assert payment.tuition_period_id == period.id
    assert payment.paid_at == datetime(2019, 9, 15, 12, 0, tzinfo=dt_timezone.utc)
    assert f"submission #{submission.id}" in payment.notes
    assert f"approved by treasurer {treasurer.email}" in payment.notes
    assert submission.details in payment.notes

    # The ledger reflects the newly minted payment.
    acct = ledger.member_account(member)
    assert acct["paid"] >= Decimal("2000.00")


def test_approve_payment_binds_dues_period_by_claimed_date(client, treasurer, member):
    period = _dues_period()
    submission = _submission(
        member, category=Payment.Type.DUES, amount=Decimal("100.00"),
        claimed_date=date(2019, 10, 1))

    resp = client.post(
        reverse("treasurer_submission_decide", args=[submission.id]),
        {"decision": "approve"})
    assert resp.status_code == 302
    submission.refresh_from_db()
    assert submission.created_payment.dues_period_id == period.id


def test_approve_charge_mints_staff_adjusted(client, treasurer, member):
    submission = _submission(
        member, kind=LedgerSubmission.Kind.CHARGE,
        category=Payment.Type.REGISTRATION, amount=Decimal("75.00"),
        claimed_date=date(2018, 3, 1),
        details="Owed a seminar fee from spring 2018, never recorded.")

    resp = client.post(
        reverse("treasurer_submission_decide", args=[submission.id]),
        {"decision": "approve"})
    assert resp.status_code == 302
    submission.refresh_from_db()

    assert submission.status == LedgerSubmission.Status.APPROVED
    assert submission.created_charge is not None
    assert submission.created_payment is None

    charge = submission.created_charge
    assert charge.user == member
    assert charge.category == Charge.Category.REGISTRATION
    assert charge.amount == Decimal("75.00")
    assert charge.effective_date == date(2018, 3, 1)
    assert charge.status == Charge.Status.OPEN
    assert charge.source == Source.SELF_REPORTED
    assert charge.staff_adjusted is True
    assert f"submission #{submission.id}" in charge.notes


def test_approve_tuition_charge_binds_period_and_sync_mints_nothing_extra(
        client, treasurer, member):
    """A dues/tuition charge must bind its period FK — the minting syncs
    key idempotency on (user, period), so a period-less charge would get
    double-minted by the next enrollment sync. Order matters: the claim is
    approved first (pre-records history, no enrollment yet); when the
    enrollment decision later lands (its post_save signal fires
    sync_tuition_charges), the sync must see the period-bound charge and
    NOT mint a second one."""
    from payments.charges import sync_tuition_charges
    from payments.models import TuitionEnrollment

    period = _tuition_period()
    submission = _submission(
        member, kind=LedgerSubmission.Kind.CHARGE,
        category=Payment.Type.TUITION, amount=Decimal("2000.00"),
        claimed_date=date(2019, 9, 15))

    resp = client.post(
        reverse("treasurer_submission_decide", args=[submission.id]),
        {"decision": "approve"})
    assert resp.status_code == 302
    submission.refresh_from_db()
    charge = submission.created_charge
    assert charge is not None
    assert charge.tuition_period_id == period.id
    assert charge.effective_date == period.start_date  # AY start, not claimed
    assert charge.staff_adjusted is True

    # The enrollment decision arrives later — its save signal runs the sync.
    TuitionEnrollment.objects.create(
        user=member, tuition_period=period,
        status=TuitionEnrollment.Status.COMMITTED)
    sync_tuition_charges(member)  # belt and suspenders: run it again directly
    assert Charge.objects.filter(
        user=member, category=Charge.Category.TUITION, tuition_period=period,
    ).exclude(status=Charge.Status.VOID).count() == 1


def test_approve_dues_charge_binds_period_and_sync_mints_nothing_extra(
        client, treasurer, member):
    from payments.charges import sync_dues_charges

    period = _dues_period()
    submission = _submission(
        member, kind=LedgerSubmission.Kind.CHARGE,
        category=Payment.Type.DUES, amount=Decimal("100.00"),
        claimed_date=date(2019, 10, 1))

    resp = client.post(
        reverse("treasurer_submission_decide", args=[submission.id]),
        {"decision": "approve"})
    assert resp.status_code == 302
    submission.refresh_from_db()
    charge = submission.created_charge
    assert charge is not None
    assert charge.dues_period_id == period.id
    assert charge.effective_date == period.start_date

    sync_dues_charges(period)
    assert Charge.objects.filter(
        user=member, category=Charge.Category.DUES, dues_period=period,
    ).exclude(status=Charge.Status.VOID).count() == 1


def test_approve_duplicate_period_charge_refused(client, treasurer, member):
    """The member already has a non-VOID charge for that (user, period) —
    refuse the approval (mirror treasurer_charge_add's duplicate guard);
    the submission stays PENDING for a decline-with-note."""
    period = _tuition_period()
    Charge.objects.create(
        user=member, category=Charge.Category.TUITION,
        amount=Decimal("2000.00"), effective_date=period.start_date,
        tuition_period=period)
    submission = _submission(
        member, kind=LedgerSubmission.Kind.CHARGE,
        category=Payment.Type.TUITION, amount=Decimal("2000.00"),
        claimed_date=date(2019, 9, 15))

    resp = client.post(
        reverse("treasurer_submission_decide", args=[submission.id]),
        {"decision": "approve"})
    assert resp.status_code == 302
    submission.refresh_from_db()
    assert submission.status == LedgerSubmission.Status.PENDING
    assert submission.created_charge is None
    assert Charge.objects.filter(
        user=member, tuition_period=period).count() == 1


def test_approve_charge_invalid_category_refused(client, treasurer, member):
    """A charge claim in a category with no Charge.Category equivalent
    (e.g. donation) can't be minted — refuse gracefully rather than 500."""
    submission = _submission(
        member, kind=LedgerSubmission.Kind.CHARGE,
        category=Payment.Type.DONATION, amount=Decimal("10.00"))

    resp = client.post(
        reverse("treasurer_submission_decide", args=[submission.id]),
        {"decision": "approve"})
    assert resp.status_code == 302
    submission.refresh_from_db()
    assert submission.status == LedgerSubmission.Status.PENDING
    assert not Charge.objects.filter(user=member).exists()


# --------------------------------------------------------- strict binding --
#
# task #439 review finding #1: a pre-records claim dated well outside any AY
# window must NOT fall back to whatever period happens to be "current" right
# now — that mis-attributes decade-old money to this AY. Contrast with
# ``_apply_category_change``'s ``_period_for`` (recategorizing an
# already-dated payment), which keeps its current()-fallback deliberately —
# that's not touched here.

def test_approve_out_of_window_dues_payment_no_period_binding(
        client, treasurer, member):
    """No DuesPeriod anywhere covers 2012 (the autouse fixture clears the
    table) — the approved payment must be minted with no dues_period FK,
    not bound to whatever's current."""
    submission = _submission(
        member, category=Payment.Type.DUES, amount=Decimal("50.00"),
        claimed_date=date(2012, 3, 1))

    resp = client.post(
        reverse("treasurer_submission_decide", args=[submission.id]),
        {"decision": "approve"})
    assert resp.status_code == 302
    submission.refresh_from_db()
    assert submission.status == LedgerSubmission.Status.APPROVED
    assert submission.created_payment.dues_period is None
    assert submission.created_payment.paid_at == datetime(
        2012, 3, 1, 12, 0, tzinfo=dt_timezone.utc)


def test_approve_out_of_window_dues_payment_does_not_block_current_dues_pay(
        client, treasurer, member):
    """The double-payment guard (has_dues_payment_for) keys off the FK — a
    decade-old claim wrongly bound to 'current' would make the member's
    real /dues/ page think this year is already paid. With the FK left
    unbound, the pay form must still show."""
    today = timezone.now().date()
    _dues_period(
        name="Current AY dues", slug="current-ay-dues-strict",
        start_date=today - timedelta(days=180),
        end_date=today + timedelta(days=180),
        due_date=today,
    )
    submission = _submission(
        member, category=Payment.Type.DUES, amount=Decimal("50.00"),
        claimed_date=date(2012, 3, 1))
    resp = client.post(
        reverse("treasurer_submission_decide", args=[submission.id]),
        {"decision": "approve"})
    assert resp.status_code == 302

    client.force_login(member)
    body = client.get(reverse("dues")).content.decode()
    assert "You're paid up" not in body


def test_approve_out_of_window_tuition_charge_no_period_binding(
        client, treasurer, member):
    """No TuitionPeriod covers 1998 — the approved charge must be minted
    with no tuition_period FK, effective_date left at the claimed date
    (not an AY start), and the duplicate-charge guard skipped entirely
    (there's no period to check against)."""
    submission = _submission(
        member, kind=LedgerSubmission.Kind.CHARGE,
        category=Payment.Type.TUITION, amount=Decimal("1500.00"),
        claimed_date=date(1998, 9, 1),
        details="Owed tuition long before any AY period was configured.")

    resp = client.post(
        reverse("treasurer_submission_decide", args=[submission.id]),
        {"decision": "approve"})
    assert resp.status_code == 302
    submission.refresh_from_db()
    assert submission.status == LedgerSubmission.Status.APPROVED
    charge = submission.created_charge
    assert charge is not None
    assert charge.tuition_period is None
    assert charge.effective_date == date(1998, 9, 1)


# --------------------------------------------------------------- decline ---

def test_decline_records_note_mints_nothing(client, treasurer, member):
    submission = _submission(member)

    resp = client.post(
        reverse("treasurer_submission_decide", args=[submission.id]),
        {"decision": "decline", "note": "No record on the old ledger either."})
    assert resp.status_code == 302
    submission.refresh_from_db()

    assert submission.status == LedgerSubmission.Status.DECLINED
    assert submission.decision_note == "No record on the old ledger either."
    assert submission.decided_by == treasurer
    assert submission.decided_at is not None
    assert submission.created_payment is None
    assert submission.created_charge is None
    assert not Payment.objects.filter(user=member).exists()


# ------------------------------------------------------------ idempotent --

def test_second_decide_is_a_noop(client, treasurer, member):
    submission = _submission(member)
    client.post(
        reverse("treasurer_submission_decide", args=[submission.id]),
        {"decision": "approve"})
    submission.refresh_from_db()
    first_payment_id = submission.created_payment_id

    resp = client.post(
        reverse("treasurer_submission_decide", args=[submission.id]),
        {"decision": "decline", "note": "changed my mind"})
    assert resp.status_code == 302
    submission.refresh_from_db()
    assert submission.status == LedgerSubmission.Status.APPROVED
    assert submission.created_payment_id == first_payment_id
    assert Payment.objects.filter(user=member).count() == 1


# --------------------------------------------------------------- notify ---

def test_approve_notifies_member(client, treasurer, member):
    submission = _submission(member)
    client.post(
        reverse("treasurer_submission_decide", args=[submission.id]),
        {"decision": "approve"})
    note = Notification.objects.get(recipient=member)
    assert "added to your account" in note.title


def test_decline_notifies_member_with_reason(client, treasurer, member):
    submission = _submission(member)
    client.post(
        reverse("treasurer_submission_decide", args=[submission.id]),
        {"decision": "decline", "note": "No matching ledger entry."})
    note = Notification.objects.get(recipient=member)
    assert "declined" in note.title
    assert "No matching ledger entry." in note.title


# ------------------------------------------------------------------ auth --

def test_non_staff_blocked(client, member):
    submission = _submission(member)
    client.force_login(member)
    resp = client.post(
        reverse("treasurer_submission_decide", args=[submission.id]),
        {"decision": "approve"})
    assert resp.status_code in (302, 403)
    submission.refresh_from_db()
    assert submission.status == LedgerSubmission.Status.PENDING


# ------------------------------------------------------------------ queue --

def test_reconcile_lists_only_pending_submissions(client, treasurer, member):
    pending = _submission(member, details="Pending claim.")
    decided = _submission(
        member, details="Already decided.",
        status=LedgerSubmission.Status.APPROVED,
    )
    resp = client.get(reverse("treasurer_reconcile"))
    assert resp.status_code == 200
    subs = resp.context["submissions"]
    assert pending in subs
    assert decided not in subs
    assert "Pending claim." in resp.content.decode()
    assert "Already decided." not in resp.content.decode()


def test_attention_queue_counts_pending_submissions(client, treasurer, member):
    _submission(member)
    _submission(member, details="A second claim.")
    _submission(member, status=LedgerSubmission.Status.DECLINED)

    resp = client.get(reverse("treasurer"))
    assert resp.context["attention"]["submission_count"] == 2
    assert "2 member-reported history submission" in resp.content.decode()


# --------------------------------------------------------------- warnings --
# task #439 review finding #4a: soft advisory badges in the Reconcile queue.

def test_reconcile_flags_duplicate_pending_submissions(client, treasurer, member):
    s1 = _submission(member, details="First filing.")
    s2 = _submission(member, details="Accidental re-filing, same everything.")

    resp = client.get(reverse("treasurer_reconcile"))
    subs = {s.id: s for s in resp.context["submissions"]}
    assert any("duplicate" in w.lower() for w in subs[s1.id].warnings)
    assert any("duplicate" in w.lower() for w in subs[s2.id].warnings)
    assert "duplicate" in resp.content.decode().lower()


def test_reconcile_no_duplicate_warning_for_unique_submission(
        client, treasurer, member):
    s = _submission(member, amount=Decimal("2000.00"))
    _submission(member, amount=Decimal("500.00"), details="A different claim.")

    resp = client.get(reverse("treasurer_reconcile"))
    subs = {row.id: row for row in resp.context["submissions"]}
    assert not any("duplicate" in w.lower() for w in subs[s.id].warnings)


def test_reconcile_flags_payment_claim_with_no_matching_charge(
        client, treasurer, member):
    period = _tuition_period()  # covers the default claimed_date 2019-09-15
    submission = _submission(member)  # payment / tuition / 2019-09-15

    resp = client.get(reverse("treasurer_reconcile"))
    row = next(s for s in resp.context["submissions"] if s.id == submission.id)
    assert any("no matching charge" in w.lower() for w in row.warnings)
    assert "no matching charge" in resp.content.decode().lower()

    # The matching charge now exists — the warning must clear.
    Charge.objects.create(
        user=member, category=Charge.Category.TUITION, tuition_period=period,
        amount=Decimal("2000.00"), effective_date=period.start_date)
    resp = client.get(reverse("treasurer_reconcile"))
    row = next(s for s in resp.context["submissions"] if s.id == submission.id)
    assert not any("no matching charge" in w.lower() for w in row.warnings)


def test_reconcile_no_charge_warning_for_registration_claims(
        client, treasurer, member):
    """The no-matching-charge heuristic is dues/tuition only (registration
    charges aren't period-bound the same way)."""
    submission = _submission(
        member, category=Payment.Type.REGISTRATION, amount=Decimal("50.00"))
    resp = client.get(reverse("treasurer_reconcile"))
    row = next(s for s in resp.context["submissions"] if s.id == submission.id)
    assert not any("no matching charge" in w.lower() for w in row.warnings)


def test_reconcile_no_charge_warning_for_charge_kind_claims(
        client, treasurer, member):
    """The heuristic only applies to *payment* claims — a charge claim is
    itself the missing charge, so there's nothing to warn about."""
    submission = _submission(
        member, kind=LedgerSubmission.Kind.CHARGE,
        category=Payment.Type.TUITION, claimed_date=date(2019, 9, 15))
    resp = client.get(reverse("treasurer_reconcile"))
    row = next(s for s in resp.context["submissions"] if s.id == submission.id)
    assert not any("no matching charge" in w.lower() for w in row.warnings)
