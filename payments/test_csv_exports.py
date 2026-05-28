"""Tests for CSV exports — roster (REG-10) and transactions (REG-15)."""

from __future__ import annotations

import csv
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from committees.models import Committee, CommitteeMembership
from events.models import Audience, Event, PriceTier, PricingCode
from payments.models import Payment, Receipt
from registrations.models import Registration


def _read_csv(response):
    return list(csv.reader(StringIO(response.content.decode("utf-8"))))


# ---- Fixtures ---------------------------------------------------------


@pytest.fixture
def event(db):
    return Event.objects.create(
        title="Seminar",
        slug="seminar",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 12, 15),
        published=True,
        status=Event.Status.OPEN,
    )


@pytest.fixture
def tier(event):
    return PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("100.00")
    )


@pytest.fixture
def staff_user(db):
    u = User.objects.create_user(email="staff@example.com", password="x")
    u.is_staff = True
    u.save()
    return u


@pytest.fixture
def random_user(db):
    return User.objects.create_user(email="r@example.com", password="x")


@pytest.fixture
def faculty(db, event):
    u = User.objects.create_user(email="fac@example.com")
    u.profile.is_faculty = True
    u.profile.save()
    event.faculty.add(u)
    return u


# ---- Roster CSV (events.event_roster_csv) -----------------------------


def test_roster_csv_forbidden_for_random_user(client, event, tier, random_user):
    client.force_login(random_user)
    response = client.get(reverse("events:roster_csv", args=[event.slug]))
    assert response.status_code == 403


def test_roster_csv_anonymous_redirects(client, event):
    response = client.get(reverse("events:roster_csv", args=[event.slug]))
    assert response.status_code == 302


def test_roster_csv_for_faculty(client, event, tier, faculty, random_user):
    Registration.objects.create(
        user=random_user, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"), status=Registration.Status.PAID,
    )
    client.force_login(faculty)
    response = client.get(reverse("events:roster_csv", args=[event.slug]))
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert "seminar-roster.csv" in response["Content-Disposition"]
    rows = _read_csv(response)
    assert rows[0] == [
        "first_name", "last_name", "email", "role",
        "tier", "amount", "status", "pricing_code", "registered_at",
    ]
    assert any("r@example.com" in row for row in rows[1:])


def test_roster_csv_excludes_cancelled_and_refunded(
    client, event, tier, faculty, random_user,
):
    Registration.objects.create(
        user=random_user, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"), status=Registration.Status.PAID,
    )
    other = User.objects.create_user(email="cancelled@example.com")
    Registration.objects.create(
        user=other, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"), status=Registration.Status.CANCELLED,
    )
    third = User.objects.create_user(email="refunded@example.com")
    Registration.objects.create(
        user=third, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"), status=Registration.Status.REFUNDED,
    )
    client.force_login(faculty)
    rows = _read_csv(client.get(reverse("events:roster_csv", args=[event.slug])))
    body = [",".join(row) for row in rows[1:]]
    assert any("r@example.com" in line for line in body)
    assert not any("cancelled@example.com" in line for line in body)
    assert not any("refunded@example.com" in line for line in body)


def test_roster_csv_for_lsp_staff_committee(client, event, tier, random_user):
    """Membership in LSP Staff committee grants roster access for any event."""
    staff_member = User.objects.create_user(email="lsp-staff@example.com")
    CommitteeMembership.objects.create(
        user=staff_member,
        committee=Committee.objects.get(slug="lsp-staff"),
        start_date=date(2026, 1, 1),
    )
    Registration.objects.create(
        user=random_user, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"), status=Registration.Status.PAID,
    )
    client.force_login(staff_member)
    response = client.get(reverse("events:roster_csv", args=[event.slug]))
    assert response.status_code == 200


def test_roster_csv_includes_pricing_code_used(
    client, event, tier, faculty, random_user,
):
    code = PricingCode.objects.create(
        event=event, issued_by=faculty,
        pricing_mode=PricingCode.Mode.PERCENT_OFF,
        amount_or_percent=Decimal("25"),
    )
    Registration.objects.create(
        user=random_user, event=event, price_tier=tier,
        pricing_code=code,
        quoted_amount=Decimal("75.00"), status=Registration.Status.PAID,
    )
    client.force_login(faculty)
    rows = _read_csv(client.get(reverse("events:roster_csv", args=[event.slug])))
    pricing_code_col = rows[0].index("pricing_code")
    assert any(row[pricing_code_col] == code.code for row in rows[1:])


# ---- Transactions CSV (payments.transactions_csv) ---------------------


def test_transactions_csv_anonymous_redirects(client):
    response = client.get(reverse("payments:transactions_csv"))
    assert response.status_code == 302


def test_transactions_csv_non_staff_forbidden(client, random_user):
    client.force_login(random_user)
    response = client.get(reverse("payments:transactions_csv"))
    assert response.status_code == 302  # user_passes_test redirects


def test_transactions_csv_all_types_listed(client, staff_user, random_user):
    Payment.objects.create(
        payment_type=Payment.Type.DUES, user=random_user,
        amount=Decimal("100.00"), status=Payment.Status.SUCCEEDED,
        paid_at=timezone.now(),
    )
    Payment.objects.create(
        payment_type=Payment.Type.DONATION, user=None, email="a@e.com",
        amount=Decimal("25.00"), status=Payment.Status.SUCCEEDED,
        paid_at=timezone.now(),
    )
    client.force_login(staff_user)
    rows = _read_csv(client.get(reverse("payments:transactions_csv")))
    headers = rows[0]
    body = rows[1:]
    assert "payment_type" in headers
    types = {row[headers.index("payment_type")] for row in body}
    assert types == {"dues", "donation"}


def test_transactions_csv_type_filter(client, staff_user, random_user):
    Payment.objects.create(
        payment_type=Payment.Type.DUES, user=random_user,
        amount=Decimal("100.00"), status=Payment.Status.SUCCEEDED,
    )
    Payment.objects.create(
        payment_type=Payment.Type.DONATION, user=random_user,
        amount=Decimal("25.00"), status=Payment.Status.SUCCEEDED,
    )
    client.force_login(staff_user)
    response = client.get(reverse("payments:transactions_csv") + "?type=donation")
    rows = _read_csv(response)
    headers = rows[0]
    body = rows[1:]
    types = {row[headers.index("payment_type")] for row in body}
    assert types == {"donation"}


def test_transactions_csv_date_range_filter(client, staff_user, random_user):
    today = timezone.now().date()
    old = Payment.objects.create(
        payment_type=Payment.Type.DUES, user=random_user,
        amount=Decimal("100.00"), status=Payment.Status.SUCCEEDED,
    )
    Payment.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(days=10),
    )
    Payment.objects.create(
        payment_type=Payment.Type.DUES, user=random_user,
        amount=Decimal("100.00"), status=Payment.Status.SUCCEEDED,
    )

    client.force_login(staff_user)
    since = (today - timedelta(days=2)).isoformat()
    response = client.get(reverse("payments:transactions_csv") + f"?since={since}")
    rows = _read_csv(response)
    body = rows[1:]
    assert len(body) == 1  # only the recent one


def test_transactions_csv_filename_includes_filters(client, staff_user):
    client.force_login(staff_user)
    response = client.get(
        reverse("payments:transactions_csv") + "?type=dues&since=2026-01-01"
    )
    cd = response["Content-Disposition"]
    assert "dues" in cd
    assert "from-2026-01-01" in cd


def test_transactions_csv_includes_receipt_number(
    client, staff_user, random_user, event, tier,
):
    reg = Registration.objects.create(
        user=random_user, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"), status=Registration.Status.PAID,
    )
    payment = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=reg, user=random_user,
        amount=Decimal("100.00"), status=Payment.Status.SUCCEEDED,
    )
    Receipt.create_for_payment(payment)

    client.force_login(staff_user)
    rows = _read_csv(client.get(reverse("payments:transactions_csv")))
    headers = rows[0]
    receipt_col = headers.index("receipt_number")
    event_col = headers.index("event_title")
    matching = [r for r in rows[1:] if r[receipt_col].startswith("LSP-")]
    assert matching
    assert matching[0][event_col] == "Seminar"
