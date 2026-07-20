"""Member statement actions log an audit row and surface to the treasurer
(task #443).

Members have full parity on their own payments (task #439) — re-categorize,
split, note — and those changes are otherwise passive. Each one now writes a
``PaymentMemberAction`` so the treasurer's Reconcile tab (and an Overview
count) can review what members changed, since a donation flip can raise
covered tuition years and self-clear the promotion gate.
"""

from datetime import date, datetime, timedelta
from datetime import timezone as tz
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from payments.models import (
    DuesPeriod,
    Payment,
    PaymentMemberAction,
    TuitionPeriod,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_periods():
    TuitionPeriod.objects.all().delete()
    DuesPeriod.objects.all().delete()


@pytest.fixture
def member(client):
    u = User.objects.create_user(email="mal@x.test", password="x")
    u.profile.role = "candidate"
    u.profile.save()
    client.force_login(u)
    return u


@pytest.fixture
def treasurer(client):
    u = User.objects.create_user(email="mal-tr@x.test", password="x", is_staff=True)
    return u


def _payment(user, ptype=Payment.Type.DONATION, amount="100", **extra):
    p = Payment.objects.create(
        user=user, payment_type=ptype, amount=Decimal(amount),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE, **extra)
    Payment.objects.filter(pk=p.pk).update(
        paid_at=datetime(2026, 10, 1, 12, tzinfo=tz.utc))
    p.refresh_from_db()
    return p


# ------------------------------------------------------------- logging ---


def test_retype_logs_a_member_action(client, member):
    period = DuesPeriod.objects.create(
        name="AY 2026-2027", slug="ay-2026-mal",
        start_date=date(2026, 9, 1), due_date=date(2026, 9, 30),
        end_date=date(2027, 8, 31),
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"),
        dues_amount_analyst=Decimal("150"))
    payment = _payment(member, ptype=Payment.Type.DONATION)

    client.post(reverse("my_payment_retype", args=[payment.id]),
                {"payment_type": "dues", "dues_period": str(period.id)})

    action = PaymentMemberAction.objects.get(payment=payment)
    assert action.action == PaymentMemberAction.Action.RETYPE
    assert action.user_id == member.id
    assert "Donation" in action.summary and "Dues" in action.summary


def test_split_logs_a_member_action(client, member):
    payment = _payment(member, ptype=Payment.Type.DONATION, amount="100")

    client.post(reverse("my_payment_split", args=[payment.id]), {
        "part_type": ["donation", "dues"],
        "part_amount": ["60", "40"],
    })

    action = PaymentMemberAction.objects.get(payment=payment)
    assert action.action == PaymentMemberAction.Action.SPLIT
    assert "$100" in action.summary


def test_note_logs_a_member_action_only_when_it_changes(client, member):
    payment = _payment(member)

    client.post(reverse("my_payment_note", args=[payment.id]),
                {"note": "Paid at the retreat."})
    assert PaymentMemberAction.objects.filter(
        payment=payment, action=PaymentMemberAction.Action.NOTE).count() == 1

    # Re-posting the identical note is a no-op — no second row.
    client.post(reverse("my_payment_note", args=[payment.id]),
                {"note": "Paid at the retreat."})
    assert PaymentMemberAction.objects.filter(
        payment=payment, action=PaymentMemberAction.Action.NOTE).count() == 1


def test_treasurer_edit_does_not_log_a_member_action(client, member, treasurer):
    """The log is for *member* self-service, not treasurer edits — the
    treasurer path must not write these rows (they'd be self-referential
    noise in the review queue)."""
    payment = _payment(member, ptype=Payment.Type.DONATION)
    period = DuesPeriod.objects.create(
        name="AY 2026-2027", slug="ay-2026-mal2",
        start_date=date(2026, 9, 1), due_date=date(2026, 9, 30),
        end_date=date(2027, 8, 31),
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"),
        dues_amount_analyst=Decimal("150"))
    client.force_login(treasurer)

    client.post(reverse("treasurer_payment_retype", args=[payment.id]),
                {"payment_type": "dues", "dues_period": str(period.id)})

    assert not PaymentMemberAction.objects.filter(payment=payment).exists()


# ------------------------------------------------- treasurer surfacing ---


def test_reconcile_lists_recent_member_actions(client, member, treasurer):
    payment = _payment(member)
    PaymentMemberAction.objects.create(
        payment=payment, user=member,
        action=PaymentMemberAction.Action.RETYPE, summary="Tuition → Donation")
    client.force_login(treasurer)

    resp = client.get(reverse("treasurer_reconcile"))
    body = resp.content.decode()
    assert "Member-changed payments" in body
    assert "Tuition → Donation" in body


def test_reconcile_excludes_actions_older_than_the_window(client, member, treasurer):
    payment = _payment(member)
    old = PaymentMemberAction.objects.create(
        payment=payment, user=member,
        action=PaymentMemberAction.Action.NOTE, summary="Ancient change")
    PaymentMemberAction.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(days=45))
    client.force_login(treasurer)

    resp = client.get(reverse("treasurer_reconcile"))
    assert "Ancient change" not in resp.content.decode()


def test_overview_counts_recent_member_actions(client, member, treasurer):
    payment = _payment(member)
    PaymentMemberAction.objects.create(
        payment=payment, user=member,
        action=PaymentMemberAction.Action.SPLIT, summary="$100 → parts")
    client.force_login(treasurer)

    resp = client.get(reverse("treasurer"))
    assert "Member-changed" in resp.content.decode()
