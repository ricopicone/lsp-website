"""Treasurer approval queue for member history submissions (task #439 §3).

Covers the Reconcile tab's "Member submissions" section and
``treasurer_submission_decide``: approve mints the matching Payment/Charge
per spec (provenance, paid_at/period binding, staff_adjusted); decline just
records a note; both are notified to the member. See
payments/test_ledger_submissions.py for the member-facing create/list half.
"""

from __future__ import annotations

from datetime import date, datetime
from datetime import timezone as dt_timezone
from decimal import Decimal

import pytest
from django.urls import reverse

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
