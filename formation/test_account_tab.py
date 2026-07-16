"""The My LSP 'My account' tab (task #439) — the member-facing view onto the
unified ledger. Replaces the old 'Dues' tab: one running balance, a
member-safe statement (no treasurer notes/provenance), the tuition-years
tile, and the existing 'Pay dues' flow reused verbatim.

See payments/test_member_account_actions.py for the treasurer-side
equivalent this mirrors, and payments/ledger.py for the account math."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, User
from formation.tabs import available_tabs
from payments.models import Charge, DuesPeriod, Payment, TuitionEnrollment, TuitionPeriod

pytestmark = pytest.mark.django_db


def _user(email, role=Profile.Role.CANDIDATE):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = role
    u.profile.save()
    return u


def _staff(email="staffacct@x.test"):
    return User.objects.create_user(email=email, password="x", is_staff=True)


# ---- 1. Renders with balance + statement -----------------------------------

def test_account_tab_shows_balance_and_statement(client):
    member = _user("acct@x.test")
    Charge.objects.create(
        user=member, category=Charge.Category.DUES, amount=Decimal("100.00"),
        effective_date=date(2026, 9, 1),
    )
    Payment.objects.create(
        user=member, payment_type=Payment.Type.DUES, amount=Decimal("40.00"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        paid_at=timezone.now(),
    )
    client.force_login(member)
    body = client.get(reverse("formation:formation") + "?tab=account").content.decode()

    assert "$60.00 owed" in body            # balance tile: 100 - 40
    assert "Sep 1, 2026" in body            # statement line date
    assert "$100.00" in body                # charge running balance
    assert "$60.00" in body                 # payment running balance


# ---- 2. Member-safety: treasurer notes never leak ---------------------------

def test_member_safety_hides_treasurer_notes(client):
    member = _user("safety@x.test")
    charge = Charge.objects.create(
        user=member, category=Charge.Category.DUES, amount=Decimal("50.00"),
        effective_date=date(2026, 9, 1), notes="TREASURER-EYES-ONLY-MARKER",
    )
    Payment.objects.create(
        user=member, payment_type=Payment.Type.DUES, amount=Decimal("10.00"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        notes="TREASURER-EYES-ONLY-MARKER", paid_at=timezone.now(),
    )

    client.force_login(member)
    member_body = client.get(
        reverse("formation:formation") + "?tab=account").content.decode()
    assert "TREASURER-EYES-ONLY-MARKER" not in member_body

    client.force_login(_staff())
    treasurer_body = client.get(
        reverse("treasurer_member_detail", args=[member.id])).content.decode()
    assert "TREASURER-EYES-ONLY-MARKER" in treasurer_body
    assert charge.notes == "TREASURER-EYES-ONLY-MARKER"  # sanity: same row


# ---- 3. Dues pay button gating ----------------------------------------------

def test_account_tab_pay_dues_button_present_when_unpaid(client):
    member = _user("duesunpaid@x.test")
    client.force_login(member)
    body = client.get(reverse("formation:formation") + "?tab=account").content.decode()
    assert "Pay $" in body
    assert "dues" in body.lower()


def test_account_tab_pay_dues_button_absent_when_paid(client):
    member = _user("duespaid@x.test")
    period = DuesPeriod.current()
    assert period is not None
    amount = period.amount_for_role(member.profile.role)
    Charge.objects.create(
        user=member, category=Charge.Category.DUES, dues_period=period,
        amount=amount, effective_date=period.start_date,
    )
    Payment.objects.create(
        user=member, payment_type=Payment.Type.DUES, dues_period=period,
        amount=amount, status=Payment.Status.SUCCEEDED,
        method=Payment.Method.OFFLINE, paid_at=timezone.now(),
    )
    client.force_login(member)
    body = client.get(reverse("formation:formation") + "?tab=account").content.decode()
    assert "Pay $" not in body
    assert "Dues paid" in body


# ---- 4. Requirement-met exemption -------------------------------------------

def _mint_four_tuition_years(member):
    for y in (2020, 2021, 2022, 2023):
        tp = TuitionPeriod.objects.create(
            name=f"AY {y}–{y + 1}", slug=f"ay-{y}-{y + 1}-reqmet-test",
            start_date=date(y, 9, 1), decision_due_date=date(y, 10, 1),
            end_date=date(y + 1, 8, 31), tuition_amount=Decimal("800.00"),
        )
        TuitionEnrollment.objects.create(
            user=member, tuition_period=tp,
            status=TuitionEnrollment.Status.COMMITTED,
        )


def test_requirement_met_hides_decision_form_on_tuition_tab(client):
    member = _user("reqmet@x.test")
    _mint_four_tuition_years(member)
    client.force_login(member)
    body = client.get(reverse("formation:formation") + "?tab=tuition").content.decode()
    assert "no further annual decision is needed" in body
    assert "Record decision" not in body


def test_requirement_met_badge_on_account_tile(client):
    member = _user("reqmet2@x.test")
    _mint_four_tuition_years(member)
    client.force_login(member)
    body = client.get(reverse("formation:formation") + "?tab=account").content.decode()
    assert "Requirement met" in body


def test_not_requirement_met_still_shows_decision_form(client, db):
    member = _user("notreqmet@x.test")
    if TuitionPeriod.current() is None:
        TuitionPeriod.objects.create(
            name="Test AY", slug="test-ay-notreqmet",
            start_date=timezone.now().date(), decision_due_date=timezone.now().date(),
            end_date=timezone.now().date(), tuition_amount=Decimal("800.00"),
        )
    client.force_login(member)
    body = client.get(reverse("formation:formation") + "?tab=tuition").content.decode()
    assert "Record decision" in body
    assert "no further annual decision is needed" not in body


# ---- 5. Tab list -------------------------------------------------------------

def test_available_tabs_shows_my_account_not_dues():
    u = _user("tablist@x.test")
    tabs = available_tabs(u, tuition=True, account=True)
    assert ("account", "My account") in tabs
    assert not any(key == "dues" for key, _ in tabs)


def test_formation_page_tab_bar_shows_my_account(client):
    member = _user("tabbar@x.test")
    client.force_login(member)
    body = client.get(reverse("formation:formation")).content
    assert b'href="?tab=account"' in body
    assert b">My account<" in body
    assert b'href="?tab=dues"' not in body
