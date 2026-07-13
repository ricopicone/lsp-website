"""Payment.transaction_date + date display/ordering in the payment tables (task #437).

Imported historical payments have ``created_at`` set to the *import* date
(auto_now_add) but ``paid_at`` set to the real payment date. The Payments tables
must show and sort by the real date, not the import date.
"""

from datetime import datetime
from datetime import timezone as dt_timezone

import pytest
from django.urls import reverse

from accounts.models import User
from payments.models import Payment


@pytest.mark.django_db
def test_transaction_date_prefers_paid_at():
    p = Payment.objects.create(
        payment_type=Payment.Type.TUITION, amount="500.00",
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
    )
    # Simulate an import: paid_at is the real (old) date; created_at is "now".
    real = datetime(2022, 9, 22, 12, 0, tzinfo=dt_timezone.utc)
    p.paid_at = real
    p.save(update_fields=["paid_at"])
    assert p.transaction_date == real


@pytest.mark.django_db
def test_transaction_date_falls_back_to_created_at_when_unpaid():
    p = Payment.objects.create(
        payment_type=Payment.Type.DUES, amount="100.00",
        status=Payment.Status.PENDING, method=Payment.Method.OFFLINE,
    )
    assert p.paid_at is None
    assert p.transaction_date == p.created_at


@pytest.fixture
def treasurer(db):
    u = User.objects.create_user(email="dt-treas@x.test", password="x")
    u.is_staff = True
    u.save()
    return u


def _imported(user, paid_iso):
    p = Payment.objects.create(
        user=user, payment_type=Payment.Type.TUITION, amount="500.00",
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        source="imported", notes="[tz-import:tuition-24-25#1]",
    )
    p.paid_at = datetime.fromisoformat(paid_iso).replace(tzinfo=dt_timezone.utc)
    p.save(update_fields=["paid_at"])
    return p


@pytest.mark.django_db
def test_member_detail_shows_real_paid_date_not_import_date(client, treasurer):
    member = User.objects.create_user(email="dt-member@x.test", password="x")
    _imported(member, "2022-09-22 12:00")
    client.force_login(treasurer)
    resp = client.get(
        reverse("treasurer_member_detail", args=[member.id]),
        SERVER_NAME="localhost",
    )
    body = resp.content.decode()
    # The rendered date is the real payment date with year (Sep 22, 2022),
    # not the import date (today).
    assert "Sep 22, 2022" in body


@pytest.mark.django_db
def test_payments_tab_orders_by_transaction_date(client, treasurer):
    member = User.objects.create_user(email="dt-m2@x.test", password="x")
    # Created in this order, but real paid dates ascend across years.
    for paid in ("2022-01-01 12:00", "2023-01-01 12:00", "2024-01-01 12:00"):
        _imported(member, paid)
    client.force_login(treasurer)
    resp = client.get(reverse("treasurer_payments"), SERVER_NAME="localhost")
    body = resp.content.decode()
    # Most recent transaction (2024) should appear before older ones.
    assert body.index("2024") < body.index("2023") < body.index("2022")


@pytest.mark.django_db
def test_transactions_csv_filters_and_sorts_by_transaction_date(client, treasurer):
    member = User.objects.create_user(email="dt-csv@x.test", password="x")
    # Imported "today" (created_at ~ now) but really paid in 2024 / 2022. The
    # paid_at date strings are unique markers for each row in the CSV body.
    _imported(member, "2024-03-15 12:00")
    _imported(member, "2022-06-01 12:00")
    client.force_login(treasurer)

    # since/until bound the REAL payment date, not the import date.
    resp = client.get(
        reverse("payments:transactions_csv") + "?since=2024-01-01&until=2024-12-31",
        SERVER_NAME="localhost",
    )
    body = resp.content.decode()
    assert "2024-03-15" in body        # the 2024 payment is included
    assert "2022-06-01" not in body    # the 2022 payment is excluded

    # Bounding the IMPORT year (2026) must NOT match these historical payments.
    resp = client.get(
        reverse("payments:transactions_csv") + "?since=2026-01-01",
        SERVER_NAME="localhost",
    )
    body = resp.content.decode()
    assert "2024-03-15" not in body
    assert "2022-06-01" not in body

    # Unfiltered export is ordered by transaction date (oldest first here).
    resp = client.get(reverse("payments:transactions_csv"), SERVER_NAME="localhost")
    body = resp.content.decode()
    assert body.index("2022-06-01") < body.index("2024-03-15")
