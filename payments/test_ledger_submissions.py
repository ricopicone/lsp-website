"""Member history-submission queue (task #439, member Account v2 §3).

A member reports a payment or charge from before the site's records begin;
the treasurer approves (minting the matching Payment/Charge) or declines it.
This file covers the member-facing half (create + own-list); the treasurer
approval/decline queue is covered in payments/test_treasurer_submissions.py.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from accounts.models import User
from payments.models import LedgerSubmission, Payment

pytestmark = pytest.mark.django_db


@pytest.fixture
def member(client):
    u = User.objects.create_user(email="submitter@x.test", password="x")
    u.profile.role = "candidate"
    u.profile.save()
    client.force_login(u)
    return u


@pytest.fixture
def other_member():
    u = User.objects.create_user(email="othersubmitter@x.test", password="x")
    u.profile.role = "candidate"
    u.profile.save()
    return u


def _valid_payload(**overrides):
    payload = {
        "kind": LedgerSubmission.Kind.PAYMENT,
        "category": Payment.Type.TUITION,
        "amount": "2000",
        "claimed_date": "2019-09-15",
        "details": "I paid $2,000 tuition in fall 2019, by check.",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------- create ---

def test_create_valid_submission(client, member):
    resp = client.post(
        reverse("my_ledger_submission_create"), _valid_payload())
    assert resp.status_code == 302
    assert "tab=account" in resp.url

    sub = LedgerSubmission.objects.get(user=member)
    assert sub.kind == LedgerSubmission.Kind.PAYMENT
    assert sub.category == Payment.Type.TUITION
    assert sub.amount == Decimal("2000.00")
    assert sub.claimed_date == date(2019, 9, 15)
    assert sub.details == "I paid $2,000 tuition in fall 2019, by check."
    assert sub.status == LedgerSubmission.Status.PENDING
    assert sub.decided_by is None
    assert sub.decided_at is None
    assert sub.created_payment is None
    assert sub.created_charge is None


def test_create_charge_kind(client, member):
    resp = client.post(
        reverse("my_ledger_submission_create"),
        _valid_payload(kind=LedgerSubmission.Kind.CHARGE,
                       category=Payment.Type.REGISTRATION, amount="50"))
    assert resp.status_code == 302
    sub = LedgerSubmission.objects.get(user=member)
    assert sub.kind == LedgerSubmission.Kind.CHARGE
    assert sub.category == Payment.Type.REGISTRATION


def test_create_rejects_bad_kind(client, member):
    resp = client.post(
        reverse("my_ledger_submission_create"),
        _valid_payload(kind="not-a-kind"))
    assert resp.status_code == 302
    assert not LedgerSubmission.objects.filter(user=member).exists()
    messages = [str(m) for m in get_messages(resp.wsgi_request)]
    assert any("payment or a charge" in m for m in messages)


def test_create_rejects_bad_category(client, member):
    resp = client.post(
        reverse("my_ledger_submission_create"),
        _valid_payload(category="not-a-category"))
    assert resp.status_code == 302
    assert not LedgerSubmission.objects.filter(user=member).exists()


def test_create_charge_donation_refused(client, member):
    """A charge claim must use a Charge.Category-compatible category —
    donation has no charge equivalent, so it's refused at create time
    (the treasurer-side decide guard stays as defense in depth)."""
    resp = client.post(
        reverse("my_ledger_submission_create"),
        _valid_payload(kind=LedgerSubmission.Kind.CHARGE,
                       category=Payment.Type.DONATION))
    assert resp.status_code == 302
    assert not LedgerSubmission.objects.filter(user=member).exists()
    messages = [str(m) for m in get_messages(resp.wsgi_request)]
    assert any("Donations can only be reported as payments" in m
               for m in messages)


def test_create_rejects_bad_amount(client, member):
    resp = client.post(
        reverse("my_ledger_submission_create"),
        _valid_payload(amount="not-a-number"))
    assert resp.status_code == 302
    assert not LedgerSubmission.objects.filter(user=member).exists()
    messages = [str(m) for m in get_messages(resp.wsgi_request)]
    assert any("positive amount" in m for m in messages)


def test_create_rejects_negative_amount(client, member):
    resp = client.post(
        reverse("my_ledger_submission_create"),
        _valid_payload(amount="-50"))
    assert resp.status_code == 302
    assert not LedgerSubmission.objects.filter(user=member).exists()


def test_create_rejects_future_date(client, member):
    from django.utils import timezone as djtz
    # Match the view's clock (timezone.now().date()) — date.today() is the
    # local calendar day and disagrees around UTC midnight (flake).
    tomorrow = (djtz.now().date() + timedelta(days=1)).isoformat()
    resp = client.post(
        reverse("my_ledger_submission_create"),
        _valid_payload(claimed_date=tomorrow))
    assert resp.status_code == 302
    assert not LedgerSubmission.objects.filter(user=member).exists()
    messages = [str(m) for m in get_messages(resp.wsgi_request)]
    assert any("future" in m for m in messages)


def test_create_accepts_today(client, member):
    from django.utils import timezone as djtz
    today = djtz.now().date().isoformat()  # the view's clock
    resp = client.post(
        reverse("my_ledger_submission_create"),
        _valid_payload(claimed_date=today))
    assert resp.status_code == 302
    assert LedgerSubmission.objects.filter(user=member).exists()


def test_create_rejects_bad_date(client, member):
    resp = client.post(
        reverse("my_ledger_submission_create"),
        _valid_payload(claimed_date="not-a-date"))
    assert resp.status_code == 302
    assert not LedgerSubmission.objects.filter(user=member).exists()


def test_create_rejects_empty_details(client, member):
    resp = client.post(
        reverse("my_ledger_submission_create"),
        _valid_payload(details="   "))
    assert resp.status_code == 302
    assert not LedgerSubmission.objects.filter(user=member).exists()
    messages = [str(m) for m in get_messages(resp.wsgi_request)]
    assert any("Describe" in m for m in messages)


def test_create_details_capped_at_2000_chars(client, member):
    resp = client.post(
        reverse("my_ledger_submission_create"),
        _valid_payload(details="x" * 2500))
    assert resp.status_code == 302
    sub = LedgerSubmission.objects.get(user=member)
    assert len(sub.details) == 2000


def test_create_refuses_at_ten_pending_submissions(client, member):
    """A guardrail against flooding the queue (task #439 review finding
    #4b) — 10 outstanding PENDING submissions is the cap; decided rows
    (approved/declined) don't count against it."""
    for i in range(10):
        LedgerSubmission.objects.create(
            user=member, kind=LedgerSubmission.Kind.PAYMENT,
            category=Payment.Type.TUITION, amount=Decimal("100.00"),
            claimed_date=date(2019, 9, 1), details=f"Claim {i}.")
    resp = client.post(
        reverse("my_ledger_submission_create"), _valid_payload())
    assert resp.status_code == 302
    assert LedgerSubmission.objects.filter(user=member).count() == 10
    messages = [str(m) for m in get_messages(resp.wsgi_request)]
    assert any("awaiting review" in m for m in messages)


def test_create_allowed_when_pending_count_below_cap_despite_decided_rows(
        client, member):
    for i in range(9):
        LedgerSubmission.objects.create(
            user=member, kind=LedgerSubmission.Kind.PAYMENT,
            category=Payment.Type.TUITION, amount=Decimal("100.00"),
            claimed_date=date(2019, 9, 1), details=f"Claim {i}.")
    for i in range(5):
        LedgerSubmission.objects.create(
            user=member, kind=LedgerSubmission.Kind.PAYMENT,
            category=Payment.Type.TUITION, amount=Decimal("100.00"),
            claimed_date=date(2019, 9, 1), details=f"Decided {i}.",
            status=LedgerSubmission.Status.APPROVED)
    resp = client.post(
        reverse("my_ledger_submission_create"), _valid_payload())
    assert resp.status_code == 302
    assert LedgerSubmission.objects.filter(user=member).count() == 15


def test_create_requires_login(client):
    resp = client.post(reverse("my_ledger_submission_create"), _valid_payload())
    assert resp.status_code == 302
    assert "/accounts/login" in resp.url
    assert not LedgerSubmission.objects.exists()


# ---------------------------------------------------------------- listing --

def test_account_tab_lists_own_submissions_with_status(client, member):
    LedgerSubmission.objects.create(
        user=member, kind=LedgerSubmission.Kind.PAYMENT,
        category=Payment.Type.DUES, amount=Decimal("100.00"),
        claimed_date=date(2020, 9, 1), details="Paid dues in cash.",
    )
    decided = LedgerSubmission.objects.create(
        user=member, kind=LedgerSubmission.Kind.PAYMENT,
        category=Payment.Type.TUITION, amount=Decimal("500.00"),
        claimed_date=date(2019, 9, 1), details="Paid partial tuition.",
        status=LedgerSubmission.Status.DECLINED,
        decision_note="No record of this on the old ledger either.",
    )
    body = client.get(
        reverse("formation:formation") + "?tab=account").content.decode()
    assert "$100.00" in body
    assert "$500.00" in body
    assert "Declined" in body
    assert decided.decision_note in body


def test_account_tab_hides_decision_note_on_approved_submission(client, member):
    """decision_note is member-visible ONLY on a decline — the guide
    promises decline-only, and an approval's note is the treasurer's own
    working note, not member-facing copy (task #439 review finding #3)."""
    LedgerSubmission.objects.create(
        user=member, kind=LedgerSubmission.Kind.PAYMENT,
        category=Payment.Type.TUITION, amount=Decimal("2000.00"),
        claimed_date=date(2019, 9, 1), details="Paid tuition in fall 2019.",
        status=LedgerSubmission.Status.APPROVED,
        decision_note="TREASURER-INTERNAL-NOTE-MARKER",
    )
    body = client.get(
        reverse("formation:formation") + "?tab=account").content.decode()
    assert "Approved" in body
    assert "TREASURER-INTERNAL-NOTE-MARKER" not in body


def test_account_tab_report_form_renders(client, member):
    body = client.get(
        reverse("formation:formation") + "?tab=account").content.decode()
    assert "Report missing history" in body
    assert reverse("my_ledger_submission_create") in body


def test_member_sees_only_own_submissions(client, member, other_member):
    LedgerSubmission.objects.create(
        user=other_member, kind=LedgerSubmission.Kind.PAYMENT,
        category=Payment.Type.TUITION, amount=Decimal("9999.00"),
        claimed_date=date(2019, 9, 1),
        details="SOMEBODY-ELSES-SUBMISSION-MARKER",
    )
    body = client.get(
        reverse("formation:formation") + "?tab=account").content.decode()
    assert "SOMEBODY-ELSES-SUBMISSION-MARKER" not in body
    assert "$9999.00" not in body


# ------------------------------------------------------------------- admin --

def test_admin_registered():
    from django.contrib import admin
    assert admin.site.is_registered(LedgerSubmission)
