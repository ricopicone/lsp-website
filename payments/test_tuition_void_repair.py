"""Repairing a tuition year whose charge was voided (task #655).

Voiding a charge stamps ``staff_adjusted=True``, and the ordinary sync never
touches a staff-adjusted row — so re-recording the year's decision used to
mint nothing and revive nothing, leaving a "Committed" year with no charge.
A VOID charge is also hidden from the statement, so there was no undo
anywhere in the interface. The treasurer's decision buttons now reconcile
that year's charge outright.
"""

import re
from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import User
from payments import ledger
from payments.models import Charge, TuitionEnrollment, TuitionPeriod

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_periods():
    TuitionPeriod.objects.all().delete()


@pytest.fixture
def treasurer(client):
    u = User.objects.create_user(email="tr@x.test", password="x", is_staff=True)
    client.force_login(u)
    return u


@pytest.fixture
def member():
    u = User.objects.create_user(email="m@x.test", password="x")
    u.profile.role = "candidate_scholar"
    u.profile.save()
    return u


def _period(start_year, amount="2000"):
    return TuitionPeriod.objects.create(
        name=f"AY {start_year}-{start_year + 1}", slug=f"t-{start_year}",
        start_date=date(start_year, 9, 1), end_date=date(start_year + 1, 8, 31),
        decision_due_date=date(start_year, 8, 31),
        tuition_amount=Decimal(amount),
    )


def _live_charge(user, period):
    return (Charge.objects
            .filter(user=user, category=Charge.Category.TUITION,
                    tuition_period=period)
            .exclude(status=Charge.Status.VOID)
            .first())


def _set_status(client, member, period, status):
    return client.post(
        reverse("treasurer_tuition_set_status", args=[member.id]),
        {"status": status, "period": period.id},
    )


def test_recommitting_revives_a_treasurer_voided_charge(client, treasurer, member):
    tp = _period(2024)
    TuitionEnrollment.objects.create(
        user=member, tuition_period=tp,
        status=TuitionEnrollment.Status.COMMITTED, source="staff")
    Charge.objects.filter(user=member, tuition_period=tp).update(
        status=Charge.Status.VOID, staff_adjusted=True)

    _set_status(client, member, tp, "committed")

    c = _live_charge(member, tp)
    assert c is not None, "the voided year's charge must come back"
    assert c.status == Charge.Status.OPEN
    assert c.amount == Decimal("2000")
    assert "Revived" in c.notes


def test_recommitting_mints_when_the_charge_row_is_gone(client, treasurer, member):
    tp = _period(2024)
    TuitionEnrollment.objects.create(
        user=member, tuition_period=tp,
        status=TuitionEnrollment.Status.COMMITTED, source="staff")
    Charge.objects.filter(user=member, tuition_period=tp).delete()

    _set_status(client, member, tp, "committed")

    assert _live_charge(member, tp).amount == Decimal("2000")


def test_repair_reaches_a_transitioned_member(client, treasurer, member):
    """Reconstructing history is exactly the case the ordinary sync refuses
    (transitioned members' tuition is frozen), so the explicit staff action
    must still work for them."""
    member.profile.role = "analyst"
    member.profile.save()
    tp = _period(2024)
    TuitionEnrollment.objects.create(
        user=member, tuition_period=tp,
        status=TuitionEnrollment.Status.COMMITTED, source="staff")
    assert _live_charge(member, tp) is None      # frozen — sync minted nothing

    _set_status(client, member, tp, "committed")

    assert _live_charge(member, tp).amount == Decimal("2000")


def test_skipping_voids_a_staff_adjusted_charge(client, treasurer, member):
    """The override runs both ways: a treasurer-adjusted charge on a year
    they then mark Skipping must stop counting."""
    tp = _period(2024)
    TuitionEnrollment.objects.create(
        user=member, tuition_period=tp,
        status=TuitionEnrollment.Status.COMMITTED, source="staff")
    Charge.objects.filter(user=member, tuition_period=tp).update(
        staff_adjusted=True)

    _set_status(client, member, tp, "skipping")

    assert _live_charge(member, tp) is None


def test_repair_leaves_other_years_voids_alone(client, treasurer, member):
    """Scoped to the clicked year — a deliberate void on another year is not
    collateral damage."""
    t23, t24 = _period(2023), _period(2024)
    for tp in (t23, t24):
        TuitionEnrollment.objects.create(
            user=member, tuition_period=tp,
            status=TuitionEnrollment.Status.COMMITTED, source="staff")
    for tp in (t23, t24):
        Charge.objects.filter(user=member, tuition_period=tp).update(
            status=Charge.Status.VOID, staff_adjusted=True)

    _set_status(client, member, t24, "committed")

    assert _live_charge(member, t24) is not None
    assert _live_charge(member, t23) is None


def test_beyond_the_cap_the_repair_mints_nothing(client, treasurer, member):
    """The four-year cap still governs: a fifth non-skipping year is never
    owed, so re-recording it must not conjure a charge."""
    periods = [_period(2021 + i) for i in range(5)]
    for tp in periods:
        TuitionEnrollment.objects.create(
            user=member, tuition_period=tp,
            status=TuitionEnrollment.Status.COMMITTED, source="staff")

    _set_status(client, member, periods[4], "committed")

    assert _live_charge(member, periods[4]) is None
    row = next(r for r in ledger.member_account(member)["tuition_rows"]
               if r["period"] == periods[4])
    assert row["state"] == "met"


# --- Removing a stray tuition-decision row -------------------------------


def _remove(client, member, period):
    return client.post(
        reverse("treasurer_tuition_remove", args=[member.id]),
        {"period": period.id}, follow=True,
    )


def test_removing_a_stray_decision_row_takes_its_charge_with_it(
        client, treasurer, member):
    tp = _period(2026, "2500")
    TuitionEnrollment.objects.create(
        user=member, tuition_period=tp,
        status=TuitionEnrollment.Status.SKIPPING, source="staff")

    _remove(client, member, tp)

    assert not TuitionEnrollment.objects.filter(
        user=member, tuition_period=tp).exists()
    assert _live_charge(member, tp) is None
    assert not any(r["period"] == tp
                   for r in ledger.member_account(member)["tuition_rows"])


def test_removing_a_year_with_money_against_it_is_refused(
        client, treasurer, member):
    """A year the member has actually paid toward is not a stray row."""
    from datetime import datetime
    from datetime import timezone as tz

    from payments.models import Payment
    tp = _period(2024)
    TuitionEnrollment.objects.create(
        user=member, tuition_period=tp,
        status=TuitionEnrollment.Status.COMMITTED, source="staff")
    p = Payment.objects.create(
        user=member, payment_type=Payment.Type.TUITION,
        amount=Decimal("2000"), status=Payment.Status.SUCCEEDED,
        method=Payment.Method.STRIPE)
    Payment.objects.filter(pk=p.pk).update(
        paid_at=datetime(2024, 10, 1, 12, tzinfo=tz.utc))

    resp = _remove(client, member, tp)

    assert TuitionEnrollment.objects.filter(
        user=member, tuition_period=tp).exists()
    assert _live_charge(member, tp) is not None
    assert b"paid" in resp.content.lower()


def test_removing_a_partly_paid_year_is_refused(client, treasurer, member):
    from datetime import datetime
    from datetime import timezone as tz

    from payments.models import Payment
    tp = _period(2024)
    TuitionEnrollment.objects.create(
        user=member, tuition_period=tp,
        status=TuitionEnrollment.Status.COMMITTED, source="staff")
    p = Payment.objects.create(
        user=member, payment_type=Payment.Type.TUITION,
        amount=Decimal("500"), status=Payment.Status.SUCCEEDED,
        method=Payment.Method.STRIPE)
    Payment.objects.filter(pk=p.pk).update(
        paid_at=datetime(2024, 10, 1, 12, tzinfo=tz.utc))

    _remove(client, member, tp)

    assert TuitionEnrollment.objects.filter(
        user=member, tuition_period=tp).exists()


def test_remove_is_staff_only(client, member):
    tp = _period(2026)
    TuitionEnrollment.objects.create(
        user=member, tuition_period=tp,
        status=TuitionEnrollment.Status.SKIPPING, source="staff")
    client.force_login(member)

    _remove(client, member, tp)

    assert TuitionEnrollment.objects.filter(
        user=member, tuition_period=tp).exists()


# --- What the treasurer's page actually offers ---------------------------


def test_page_shows_no_charge_and_offers_a_one_click_repair(
        client, treasurer, member):
    """The row must not read "Requirement met", and Committed must be live —
    the old page disabled it on a committed row, so repairing a voided year
    took a Skipping round-trip."""
    tp = _period(2024)
    TuitionEnrollment.objects.create(
        user=member, tuition_period=tp,
        status=TuitionEnrollment.Status.COMMITTED, source="staff")
    Charge.objects.filter(user=member, tuition_period=tp).update(
        status=Charge.Status.VOID, staff_adjusted=True)

    body = client.get(
        reverse("treasurer_member_detail", args=[member.id])
    ).content.decode()
    assert "No charge" in body
    assert "Requirement met" not in body
    assert ">Committed</button>" in body
    assert "disabled>Committed</button>" not in body


def test_page_offers_remove_and_withholds_it_from_a_paid_year(
        client, treasurer, member):
    from datetime import datetime
    from datetime import timezone as tz

    from payments.models import Payment
    stray, paid_year = _period(2026, "2500"), _period(2024)
    TuitionEnrollment.objects.create(
        user=member, tuition_period=stray,
        status=TuitionEnrollment.Status.SKIPPING, source="staff")
    TuitionEnrollment.objects.create(
        user=member, tuition_period=paid_year,
        status=TuitionEnrollment.Status.COMMITTED, source="staff")
    p = Payment.objects.create(
        user=member, payment_type=Payment.Type.TUITION,
        amount=Decimal("2000"), status=Payment.Status.SUCCEEDED,
        method=Payment.Method.STRIPE)
    Payment.objects.filter(pk=p.pk).update(
        paid_at=datetime(2024, 10, 1, 12, tzinfo=tz.utc))

    body = client.get(
        reverse("treasurer_member_detail", args=[member.id])
    ).content.decode()
    assert reverse("treasurer_tuition_remove", args=[member.id]) in body
    # Two Remove buttons — the paid year's is disabled, the stray one's isn't.
    buttons = re.findall(
        r'aria-label="Remove this year"(.*?)>', body, flags=re.S)
    assert len(buttons) == 2
    assert sum("disabled" in b for b in buttons) == 1
