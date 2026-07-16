"""Unified-ledger math: one fungible pot swept oldest-first (task #439)."""

from datetime import date, datetime
from datetime import timezone as tz
from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.models import User
from payments import ledger
from payments.models import (
    Charge,
    DuesPeriod,
    Payment,
    TuitionEnrollment,
    TuitionPeriod,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_periods():
    TuitionPeriod.objects.all().delete()
    DuesPeriod.objects.all().delete()


@pytest.fixture
def member():
    u = User.objects.create_user(email="lg@x.test", password="x")
    u.profile.role = "candidate"  # in-training: tuition history isn't frozen
    u.profile.save()
    return u


def _dues_period(start_year, **amounts):
    return DuesPeriod.objects.create(
        name=f"AY {start_year}-{start_year + 1}", slug=f"ay-{start_year}-{start_year + 1}",
        start_date=date(start_year, 9, 1), due_date=date(start_year, 9, 30),
        end_date=date(start_year + 1, 8, 31),
        dues_amount_pre_candidate=amounts.get("pre", Decimal("50")),
        dues_amount_candidate=amounts.get("cand", Decimal("100")),
        dues_amount_analyst=amounts.get("analyst", Decimal("150")),
    )


def _tuition_period(start_year, amount):
    return TuitionPeriod.objects.create(
        name=f"AY {start_year}-{start_year + 1} T", slug=f"t-{start_year}",
        start_date=date(start_year, 9, 1), end_date=date(start_year + 1, 8, 31),
        decision_due_date=date(start_year, 8, 31), tuition_amount=Decimal(amount),
    )


def _charge(user, category, amount, eff, **kw):
    return Charge.objects.create(
        user=user, category=category, amount=Decimal(amount),
        effective_date=eff, **kw,
    )


def _pay(user, ptype, amount, when, status=Payment.Status.SUCCEEDED):
    p = Payment.objects.create(
        user=user, payment_type=ptype, amount=Decimal(amount), status=status,
        method=Payment.Method.STRIPE,
    )
    Payment.objects.filter(pk=p.pk).update(paid_at=when)
    return p


WHEN = datetime(2026, 9, 14, 12, tzinfo=tz.utc)


def test_fungible_net_balance_across_categories(member):
    """A dues overpayment covers tuition — one pot, one balance."""
    _charge(member, Charge.Category.DUES, "100", date(2026, 9, 1))
    _charge(member, Charge.Category.TUITION, "1500", date(2026, 9, 1))
    _pay(member, Payment.Type.DUES, "150", WHEN)
    _pay(member, Payment.Type.TUITION, "1450", WHEN)
    acct = ledger.member_account(member)
    assert acct["obligation"] == Decimal("1600")
    assert acct["paid"] == Decimal("1600")
    assert acct["balance"] == Decimal("0")
    assert acct["owes"] == Decimal("0") and acct["credit"] == Decimal("0")


def test_sweep_covers_oldest_charge_first(member):
    old = _charge(member, Charge.Category.DUES, "100", date(2024, 9, 1))
    new = _charge(member, Charge.Category.DUES, "100", date(2026, 9, 1))
    _pay(member, Payment.Type.DUES, "150", WHEN)
    acct = ledger.member_account(member)
    assert acct["charge_states"][old.id] == "paid"
    assert acct["charge_states"][new.id] == "partial"


def test_waived_and_void_charges_do_not_count(member):
    _charge(member, Charge.Category.DUES, "100", date(2026, 9, 1),
            status=Charge.Status.WAIVED)
    _charge(member, Charge.Category.DUES, "100", date(2026, 9, 1),
            status=Charge.Status.VOID)
    acct = ledger.member_account(member)
    assert acct["obligation"] == Decimal("0")
    # WAIVED shows on the statement (delta 0); VOID is omitted entirely.
    kinds = [(ln["obj"].status if ln["kind"] == "charge" else None)
             for ln in acct["lines"]]
    assert Charge.Status.WAIVED in kinds
    assert Charge.Status.VOID not in kinds


def test_donations_refunds_and_pending_never_offset(member):
    _charge(member, Charge.Category.DUES, "100", date(2026, 9, 1))
    _pay(member, Payment.Type.DONATION, "500", WHEN)
    _pay(member, Payment.Type.DUES, "100", WHEN, status=Payment.Status.REFUNDED)
    _pay(member, Payment.Type.DUES, "100", WHEN, status=Payment.Status.PENDING)
    acct = ledger.member_account(member)
    assert acct["paid"] == Decimal("0")
    assert acct["owes"] == Decimal("100")
    # Donation still appears as a statement line that doesn't count.
    donation_lines = [ln for ln in acct["lines"]
                      if ln["kind"] == "payment"
                      and ln["obj"].payment_type == Payment.Type.DONATION]
    assert donation_lines and donation_lines[0]["counts"] is False


def test_running_balance_on_statement(member):
    _charge(member, Charge.Category.DUES, "100", date(2026, 9, 1))
    _pay(member, Payment.Type.DUES, "60", WHEN)
    acct = ledger.member_account(member)
    assert [ln["running"] for ln in acct["lines"]] == [Decimal("100"), Decimal("40")]


def test_tuition_progress_counts_covered_tuition_charges(member):
    t24 = _tuition_period(2024, "2000")
    t25 = _tuition_period(2025, "2000")
    _charge(member, Charge.Category.TUITION, "2000", t24.start_date, tuition_period=t24)
    _charge(member, Charge.Category.TUITION, "2000", t25.start_date, tuition_period=t25)
    _pay(member, Payment.Type.TUITION, "2500", WHEN)
    acct = ledger.member_account(member)
    assert acct["tuition_years_covered"] == 1
    assert acct["tuition_years_required"] == 4
    assert acct["total_tuition_paid"] == Decimal("2500")


def test_tuition_rows_carry_enrollment_decisions(member):
    t25 = _tuition_period(2025, "2000")
    t26 = _tuition_period(2026, "2000")
    TuitionEnrollment.objects.create(
        user=member, tuition_period=t25,
        status=TuitionEnrollment.Status.SKIPPING, source="staff")
    TuitionEnrollment.objects.create(
        user=member, tuition_period=t26,
        status=TuitionEnrollment.Status.COMMITTED, source="staff")
    # Signal (Task 5) creates the charge automatically; no manual creation needed
    acct = ledger.member_account(member)
    by_slug = {r["period"].slug: r["state"] for r in acct["tuition_rows"]}
    assert by_slug["t-2025"] == "skipping"
    assert by_slug["t-2026"] == "unpaid"


def test_enrollment_beyond_cap_reads_met(member):
    periods = [_tuition_period(2021 + i, "2000") for i in range(5)]
    for tp in periods:
        TuitionEnrollment.objects.create(
            user=member, tuition_period=tp,
            status=TuitionEnrollment.Status.COMMITTED, source="staff")
    # Signal (Task 5) creates charges only for the first four non-skipping years
    acct = ledger.member_account(member)
    by_slug = {r["period"].slug: r["state"] for r in acct["tuition_rows"]}
    assert by_slug["t-2025"] == "met"   # 5th non-skipping year — never owed


def test_conflict_flag_credit_plus_skipping_year(member):
    t25 = _tuition_period(2025, "2000")
    TuitionEnrollment.objects.create(
        user=member, tuition_period=t25,
        status=TuitionEnrollment.Status.SKIPPING, source="staff")
    _pay(member, Payment.Type.TUITION, "2000", WHEN)
    acct = ledger.member_account(member)
    assert acct["credit"] == Decimal("2000")
    assert acct["conflict"] is True


def test_dues_state_for_current_period(member):
    # Build a dues period covering *today* — dues_state keys off
    # DuesPeriod.current(), which is date-sensitive.
    today = timezone.now().date()
    start = today.year if today.month >= 9 else today.year - 1
    p = _dues_period(start)
    c = _charge(member, Charge.Category.DUES, "100", p.start_date, dues_period=p)
    acct = ledger.member_account(member)
    assert acct["dues_state"] == "unpaid"
    _pay(member, Payment.Type.DUES, "100", WHEN)
    assert ledger.member_account(member)["dues_state"] == "paid"
    c.status = Charge.Status.WAIVED
    c.save()
    assert ledger.member_account(member)["dues_state"] == "waived"


def test_zero_amount_open_charge_reads_paid(member):
    c = _charge(member, Charge.Category.REGISTRATION, "0", date(2026, 9, 1))
    acct = ledger.member_account(member)
    assert acct["charge_states"][c.id] == "paid"


def test_accounts_overview_rows_and_ordering(member):
    other = User.objects.create_user(email="lg2@x.test", password="x")
    today = timezone.now().date()
    start = today.year if today.month >= 9 else today.year - 1
    p = _dues_period(start)
    _charge(member, Charge.Category.DUES, "100", p.start_date, dues_period=p)
    _charge(other, Charge.Category.DUES, "100", p.start_date, dues_period=p)
    _pay(other, Payment.Type.DUES, "100", WHEN)
    rows = ledger.accounts_overview()
    assert [r["user"].email for r in rows] == ["lg@x.test", "lg2@x.test"]  # owed first
    assert rows[0]["owes"] == Decimal("100")
    assert rows[1]["balance"] == Decimal("0")
    assert rows[1]["dues_state"] == "paid"
    assert rows[1]["last_payment"] is not None


def test_accounts_overview_excludes_personas(member):
    """Training-sandbox personas must not appear on the Accounts tab or
    balances CSV (task #439 fix 4a; mirrors the reconcile-autocomplete
    persona filter)."""
    persona = User.objects.create_user(email="persona-lg@x.test", password="x")
    persona.profile.is_persona = True
    persona.profile.save()
    today = timezone.now().date()
    start = today.year if today.month >= 9 else today.year - 1
    p = _dues_period(start)
    _charge(persona, Charge.Category.DUES, "100", p.start_date, dues_period=p)
    rows = ledger.accounts_overview()
    assert persona.email not in [r["user"].email for r in rows]


def test_accounts_overview_includes_payment_only_members(member):
    _pay(member, Payment.Type.TUITION, "500", WHEN)
    rows = ledger.accounts_overview()
    assert rows and rows[0]["credit"] == Decimal("500")


def test_accounts_overview_query_count(member, django_assert_max_num_queries):
    p = _dues_period(2026)
    for i in range(10):
        u = User.objects.create_user(email=f"bulk{i}@x.test", password="x")
        _charge(u, Charge.Category.DUES, "100", p.start_date, dues_period=p)
        _pay(u, Payment.Type.DUES, "40", WHEN)
    with django_assert_max_num_queries(8):
        ledger.accounts_overview()


def test_collected_this_ay_groups_by_category(member):
    _dues_period(2026)
    _pay(member, Payment.Type.DUES, "100", WHEN)
    _pay(member, Payment.Type.TUITION, "2000", WHEN)
    _pay(member, Payment.Type.DONATION, "50", WHEN)  # donations reported too
    out = ledger.collected_this_ay(today=date(2026, 9, 20))
    assert out["by_category"][Payment.Type.DUES] == Decimal("100")
    assert out["by_category"][Payment.Type.TUITION] == Decimal("2000")
    assert out["by_category"][Payment.Type.DONATION] == Decimal("50")
    assert out["total"] == Decimal("2150")


def test_conflict_is_tuition_scoped_not_cross_category(member):
    """Dues overpayment + a skipping tuition year is NOT a conflict — skipping
    is a tuition-only concept; dues/registrations are owed regardless (#439)."""
    t25 = _tuition_period(2025, "2000")
    TuitionEnrollment.objects.create(
        user=member, tuition_period=t25,
        status=TuitionEnrollment.Status.SKIPPING, source="staff")
    _pay(member, Payment.Type.DUES, "100", WHEN)   # cross-category credit only
    acct = ledger.member_account(member)
    assert acct["credit"] == Decimal("100")
    assert acct["conflict"] is False
    assert acct["tuition_overpaid"] == Decimal("0")


def test_conflict_fires_on_tuition_overpay_with_skipping(member):
    t25 = _tuition_period(2025, "2000")
    TuitionEnrollment.objects.create(
        user=member, tuition_period=t25,
        status=TuitionEnrollment.Status.SKIPPING, source="staff")
    _pay(member, Payment.Type.TUITION, "500", WHEN)
    acct = ledger.member_account(member)
    assert acct["conflict"] is True
    assert acct["tuition_overpaid"] == Decimal("500")


def test_accounts_overview_conflict_is_tuition_scoped(member):
    t25 = _tuition_period(2025, "2000")
    TuitionEnrollment.objects.create(
        user=member, tuition_period=t25,
        status=TuitionEnrollment.Status.SKIPPING, source="staff")
    _pay(member, Payment.Type.DUES, "100", WHEN)
    other = User.objects.create_user(email="lg3@x.test", password="x")
    TuitionEnrollment.objects.create(
        user=other, tuition_period=t25,
        status=TuitionEnrollment.Status.SKIPPING, source="staff")
    _pay(other, Payment.Type.TUITION, "500", WHEN)
    by = {r["user"].email: r for r in ledger.accounts_overview()}
    assert by["lg@x.test"]["conflict"] is False        # dues credit only
    assert by["lg3@x.test"]["conflict"] is True        # tuition overpay
    assert by["lg3@x.test"]["tuition_overpaid"] == Decimal("500")


def test_covered_year_decision_label_reads_paid(member):
    """A COMMITTED decision whose year the sweep fully covers displays as
    'Paid' — the record itself is untouched (task #439)."""
    t25 = _tuition_period(2025, "2000")
    e = TuitionEnrollment.objects.create(
        user=member, tuition_period=t25,
        status=TuitionEnrollment.Status.COMMITTED, source="staff")
    _pay(member, Payment.Type.TUITION, "2000", WHEN)
    acct = ledger.member_account(member)
    row = acct["tuition_rows"][0]
    assert row["state"] == "paid"
    assert row["decision_label"] == "Paid"
    e.refresh_from_db()
    assert e.status == TuitionEnrollment.Status.COMMITTED  # record untouched


def test_uncovered_year_decision_label_is_the_decision(member):
    t25 = _tuition_period(2025, "2000")
    TuitionEnrollment.objects.create(
        user=member, tuition_period=t25,
        status=TuitionEnrollment.Status.COMMITTED, source="staff")
    acct = ledger.member_account(member)
    assert acct["tuition_rows"][0]["decision_label"] == "Committed (will pay)"
