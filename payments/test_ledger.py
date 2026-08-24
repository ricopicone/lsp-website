"""Unified-ledger math: money swept oldest-first, category-scoped then
spilling across categories (task #439, re-scoped by task #473)."""

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
    """The *account* stays fully fungible: one obligation, one paid total, one
    balance across every category. Only the per-category coverage read off it
    is bucketed (task #473)."""
    _charge(member, Charge.Category.DUES, "100", date(2026, 9, 1))
    _charge(member, Charge.Category.TUITION, "1500", date(2026, 9, 1))
    _pay(member, Payment.Type.DUES, "150", WHEN)
    _pay(member, Payment.Type.TUITION, "1450", WHEN)
    acct = ledger.member_account(member)
    assert acct["obligation"] == Decimal("1600")
    assert acct["paid"] == Decimal("1600")
    assert acct["balance"] == Decimal("0")
    assert acct["owes"] == Decimal("0") and acct["credit"] == Decimal("0")


def test_registration_money_never_covers_an_older_tuition_year(member):
    """Task #473: the sweep is category-scoped first.

    A registration fee paid in full at the time must settle *its own* charge,
    not get retro-credited to an older unpaid tuition year — which is what a
    category-blind oldest-first sweep did (Rico's account read
    "$1,870 / $2,000" on a tuition year with only $6,000 of tuition payments
    on the ledger).
    """
    tuition = _charge(member, Charge.Category.TUITION, "2000", date(2023, 9, 1))
    reg = _charge(member, Charge.Category.REGISTRATION, "560", date(2026, 1, 20))
    _pay(member, Payment.Type.REGISTRATION, "560", WHEN)
    acct = ledger.member_account(member)
    assert acct["charge_states"][reg.id] == "paid"
    assert acct["charge_states"][tuition.id] == "unpaid"
    assert acct["charge_covered"][tuition.id] == Decimal("0")
    # Net balance is unchanged by the re-attribution.
    assert acct["balance"] == Decimal("2000")


def test_tuition_years_covered_ignores_settled_other_category_money(member):
    """The promotion gate / "requirement met" count must not be advanced by
    registration money that is doing its own job — paying a registration fee.
    """
    for year in (2022, 2023):
        tp = _tuition_period(year, "2000")
        _charge(member, Charge.Category.TUITION, "2000", tp.start_date,
                tuition_period=tp)
    _charge(member, Charge.Category.REGISTRATION, "2000", date(2026, 1, 20))
    _pay(member, Payment.Type.TUITION, "2000", WHEN)
    _pay(member, Payment.Type.REGISTRATION, "2000", WHEN)
    acct = ledger.member_account(member)
    assert acct["tuition_years_covered"] == 1


def test_surplus_in_another_category_never_advances_tuition_years(member):
    """No fungibility in the meta accounting, even for a genuine surplus: a
    registration payment with no registration charge is real credit on the
    account — it shows in the balance — but it is not tuition money and must
    never cover a tuition year."""
    for year in (2022, 2023):
        tp = _tuition_period(year, "2000")
        _charge(member, Charge.Category.TUITION, "2000", tp.start_date,
                tuition_period=tp)
    _pay(member, Payment.Type.TUITION, "2000", WHEN)
    _pay(member, Payment.Type.REGISTRATION, "2000", WHEN)  # no reg charge
    acct = ledger.member_account(member)
    assert acct["tuition_years_covered"] == 1
    # The ledger — the ground truth — still nets it: $4,000 owed, $4,000 paid.
    assert acct["balance"] == Decimal("0")


def test_task_473_reported_account_shape(member):
    """The account that surfaced this (task #473), replayed from prod.

    Reported symptom: three tuition years fully paid *plus* "$1,870.00 /
    $2,000.00" on a fourth, against only $6,000 of tuition payments on the
    ledger. The $1,870 was precisely the member's non-tuition money ($400
    dues + $1,570 registration) minus the one dues charge that happened to
    sort ahead of the last tuition year.
    """
    tuition_years = [(2020, "2000"), (2021, "2000"), (2022, "2000"),
                     (2023, "2000")]
    charges = {}
    for year, amount in tuition_years:
        tp = _tuition_period(year, amount)
        charges[year] = _charge(member, Charge.Category.TUITION, amount,
                                tp.start_date, tuition_period=tp)
    for year in (2022, 2023, 2024, 2025):
        _charge(member, Charge.Category.DUES, "100", date(year, 9, 1))
    for amount, eff in [("350", date(2024, 12, 4)), ("560", date(2026, 1, 20)),
                        ("560", date(2026, 7, 23)), ("100", date(2026, 7, 24))]:
        _charge(member, Charge.Category.REGISTRATION, amount, eff)

    for amount, when in [("2000", datetime(2021, 8, 19, tzinfo=tz.utc)),
                         ("2000", datetime(2022, 9, 8, tzinfo=tz.utc)),
                         ("1000", datetime(2023, 9, 25, tzinfo=tz.utc)),
                         ("1000", datetime(2024, 5, 9, tzinfo=tz.utc))]:
        _pay(member, Payment.Type.TUITION, amount, when)
    for when in [datetime(2022, 9, 29, tzinfo=tz.utc),
                 datetime(2023, 9, 25, tzinfo=tz.utc),
                 datetime(2024, 12, 3, tzinfo=tz.utc),
                 datetime(2026, 1, 20, tzinfo=tz.utc)]:
        _pay(member, Payment.Type.DUES, "100", when)
    for amount, when in [("350", datetime(2024, 12, 4, tzinfo=tz.utc)),
                         ("560", datetime(2026, 1, 20, tzinfo=tz.utc)),
                         ("560", datetime(2026, 7, 23, tzinfo=tz.utc)),
                         ("100", datetime(2026, 7, 24, tzinfo=tz.utc))]:
        _pay(member, Payment.Type.REGISTRATION, amount, when)

    acct = ledger.member_account(member)
    # Unchanged by the fix, and correct all along: one unpaid tuition year.
    assert acct["paid"] == Decimal("7970")
    assert acct["obligation"] == Decimal("9970")
    assert acct["balance"] == Decimal("2000")
    # Three tuition years covered by $6,000 of tuition money — no leak.
    assert acct["total_tuition_paid"] == Decimal("6000")
    assert acct["tuition_years_covered"] == 3
    assert acct["charge_covered"][charges[2023].id] == Decimal("0")
    assert acct["charge_states"][charges[2023].id] == "unpaid"
    # Every dues and registration charge reads paid — they were, at the time.
    assert all(
        acct["charge_states"][c.id] == "paid"
        for c in Charge.objects.filter(user=member).exclude(
            category=Charge.Category.TUITION)
    )


def test_dues_surplus_never_covers_tuition(member):
    """A dues overpayment stays dues credit. It shows on the account (the
    balance drops) but it does not settle a tuition charge."""
    tuition = _charge(member, Charge.Category.TUITION, "2000", date(2024, 9, 1))
    dues = _charge(member, Charge.Category.DUES, "100", date(2026, 9, 1))
    _pay(member, Payment.Type.DUES, "600", WHEN)  # $500 over on dues
    acct = ledger.member_account(member)
    assert acct["charge_states"][dues.id] == "paid"
    assert acct["charge_covered"][tuition.id] == Decimal("0")
    assert acct["charge_states"][tuition.id] == "unpaid"
    # Ground truth is unchanged: $2,100 owed less $600 paid.
    assert acct["balance"] == Decimal("1500")
    assert acct["dues_credit"] == Decimal("500")


def test_payment_in_a_category_with_no_charges_covers_nothing(member):
    """Money in a category the member has no charges in settles nothing —
    it is simply credit on the account."""
    tuition = _charge(member, Charge.Category.TUITION, "2000", date(2024, 9, 1))
    _pay(member, Payment.Type.DUES, "300", WHEN)
    acct = ledger.member_account(member)
    assert acct["charge_covered"][tuition.id] == Decimal("0")
    assert acct["balance"] == Decimal("1700")


def test_dues_bucket_totals_and_rows(member):
    """Dues gets the same bucket treatment as tuition: a cumulative dues
    obligation against dues money only, plus per-year rows."""
    for year in (2024, 2025, 2026):
        p = _dues_period(year)
        _charge(member, Charge.Category.DUES, "100", p.start_date,
                dues_period=p)
    _pay(member, Payment.Type.DUES, "250", WHEN)
    _pay(member, Payment.Type.TUITION, "5000", WHEN)  # never touches dues
    acct = ledger.member_account(member)
    assert acct["dues_obligation"] == Decimal("300")
    assert acct["total_dues_paid"] == Decimal("250")
    assert acct["dues_balance"] == Decimal("50")
    assert acct["dues_owed"] == Decimal("50")
    assert acct["dues_credit"] == Decimal("0")
    # Newest-first rows, oldest-first coverage within the bucket.
    assert [r["state"] for r in acct["dues_rows"]] == ["partial", "paid", "paid"]
    assert [r["period"].start_date.year for r in acct["dues_rows"]] == [
        2026, 2025, 2024]


def test_dues_bucket_on_accounts_overview(member):
    """The batched roster carries the same dues bucket figures."""
    today = timezone.localdate()
    p = _dues_period(today.year if today.month >= 9 else today.year - 1)
    _charge(member, Charge.Category.DUES, "100", p.start_date, dues_period=p)
    _pay(member, Payment.Type.TUITION, "5000", WHEN)
    row = next(r for r in ledger.accounts_overview()
               if r["user"].id == member.id)
    assert row["dues_obligation"] == Decimal("100")
    assert row["dues_owed"] == Decimal("100")   # tuition money doesn't pay dues
    assert row["dues_state"] == "unpaid"
    assert row["credit"] == Decimal("4900")     # ...but the account nets it


def test_accounts_overview_sweep_is_category_scoped(member):
    """The batched roster sweep matches the per-member one (task #473)."""
    _charge(member, Charge.Category.TUITION, "2000", date(2023, 9, 1))
    _charge(member, Charge.Category.REGISTRATION, "2500", date(2026, 1, 20))
    _pay(member, Payment.Type.REGISTRATION, "2500", WHEN)
    row = next(r for r in ledger.accounts_overview()
               if r["user"].id == member.id)
    assert row["tuition_covered"] == 0  # category-blind sweep counted it as 1
    assert row["balance"] == Decimal("2000")


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


def test_tuition_rows_carry_coverage_for_the_progress_bar(member):
    """Each charge-backed tuition row exposes covered + pct so the treasurer
    table can draw a fill bar instead of a bare Paid/Partial badge."""
    _tuition_period(2026, "2000")
    TuitionEnrollment.objects.create(
        user=member, tuition_period=TuitionPeriod.objects.get(slug="t-2026"),
        status=TuitionEnrollment.Status.COMMITTED, source="staff")
    _pay(member, Payment.Type.TUITION, "500", WHEN)
    acct = ledger.member_account(member)
    row = next(r for r in acct["tuition_rows"] if r["period"].slug == "t-2026")
    assert row["state"] == "partial"
    assert row["covered"] == Decimal("500")
    assert row["pct"] == 25


def test_skipping_row_has_no_progress_bar(member):
    """A skipping year carries no charge, so no fill bar (pct is None)."""
    _tuition_period(2026, "2000")
    TuitionEnrollment.objects.create(
        user=member, tuition_period=TuitionPeriod.objects.get(slug="t-2026"),
        status=TuitionEnrollment.Status.SKIPPING, source="staff")
    acct = ledger.member_account(member)
    row = next(r for r in acct["tuition_rows"] if r["period"].slug == "t-2026")
    assert row["state"] == "skipping"
    assert row["pct"] is None


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


def test_decision_exempt_via_paid_charges_with_no_enrollments(member):
    """Four years' worth of tuition charges, fully paid off, with NO
    TuitionEnrollment rows at all (e.g. minted from approved pre-records
    history submissions for a member who started before enrollments were
    tracked) — decision-exempt via the paid-met OR, not just the
    enrollment-count path (task #439 review finding #2)."""
    for y in (2016, 2017, 2018, 2019):
        _charge(member, Charge.Category.TUITION, "800", date(y, 9, 1))
    _pay(member, Payment.Type.TUITION, "3200", WHEN)
    assert TuitionEnrollment.objects.filter(user=member).count() == 0
    acct = ledger.member_account(member)
    assert acct["tuition_years_covered"] == 4
    assert ledger.tuition_decision_exempt(member) is True


def test_not_decision_exempt_with_partial_charges_and_no_enrollments(member):
    """Same shape, but only 3 of the 4 years are actually paid off — not
    exempt (the paid-met path requires the full four, same as the
    enrollment-count path)."""
    for y in (2016, 2017, 2018, 2019):
        _charge(member, Charge.Category.TUITION, "800", date(y, 9, 1))
    _pay(member, Payment.Type.TUITION, "2400", WHEN)  # 3 years' worth
    acct = ledger.member_account(member)
    assert acct["tuition_years_covered"] == 3
    assert ledger.tuition_decision_exempt(member) is False


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
    today = timezone.localdate()
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
    today = timezone.localdate()
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
    today = timezone.localdate()
    start = today.year if today.month >= 9 else today.year - 1
    p = _dues_period(start)
    _charge(persona, Charge.Category.DUES, "100", p.start_date, dues_period=p)
    rows = ledger.accounts_overview()
    assert persona.email not in [r["user"].email for r in rows]


def test_accounts_overview_includes_payment_only_members(member):
    _pay(member, Payment.Type.TUITION, "500", WHEN)
    rows = ledger.accounts_overview()
    assert rows and rows[0]["credit"] == Decimal("500")


def test_accounts_overview_includes_reminder_history(member):
    """Owing rows carry balance-reminder history — count + most recent send,
    batched (not N+1) alongside the rest of accounts_overview (task #450
    phase D)."""
    from payments.models import BalanceReminder

    other = User.objects.create_user(email="lg-noreminders@x.test", password="x")
    p = _dues_period(2026)
    _charge(member, Charge.Category.DUES, "100", p.start_date, dues_period=p)
    _charge(other, Charge.Category.DUES, "100", p.start_date, dues_period=p)
    BalanceReminder.objects.create(user=member, balance=Decimal("100"))
    later = BalanceReminder.objects.create(user=member, balance=Decimal("100"))
    BalanceReminder.objects.filter(pk=later.pk).update(
        sent_at=datetime(2026, 10, 9, tzinfo=tz.utc))

    by_email = {r["user"].email: r for r in ledger.accounts_overview()}
    assert by_email[member.email]["reminder_count"] == 2
    assert by_email[member.email]["last_reminded"] == datetime(2026, 10, 9, tzinfo=tz.utc)
    assert by_email[other.email]["reminder_count"] == 0
    assert by_email[other.email]["last_reminded"] is None


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


def test_covered_year_reads_paid_for_a_pending_plan_request(member):
    """A PLAN_REQUESTED year the sweep fully covers reads 'Paid' rather than a
    stale 'Payment plan requested' (task #484)."""
    t25 = _tuition_period(2025, "2000")
    TuitionEnrollment.objects.create(
        user=member, tuition_period=t25,
        status=TuitionEnrollment.Status.PLAN_REQUESTED, source="staff")
    _pay(member, Payment.Type.TUITION, "2000", WHEN)
    row = ledger.member_account(member)["tuition_rows"][0]
    assert row["state"] == "paid"
    assert row["decision_label"] == "Paid"


def test_uncovered_year_decision_label_is_the_decision(member):
    t25 = _tuition_period(2025, "2000")
    TuitionEnrollment.objects.create(
        user=member, tuition_period=t25,
        status=TuitionEnrollment.Status.COMMITTED, source="staff")
    acct = ledger.member_account(member)
    assert acct["tuition_rows"][0]["decision_label"] == "Committed (will pay)"


# --- one definition of "counts toward the pot" (task #443) --------------


def test_counting_payments_q_matches_the_python_predicate(member):
    """``COUNTING_PAYMENTS`` (queryset) and ``_counts`` (in-memory) are a
    matched pair — they must agree over every status × type combination, or
    the batched ``accounts_overview`` and the per-member ``member_account``
    would quietly disagree about what a member has paid."""
    made = []
    for status in Payment.Status.values:
        for ptype in Payment.Type.values:
            made.append(_pay(member, ptype, "10", WHEN, status=status))

    by_q = set(
        Payment.objects.filter(ledger.COUNTING_PAYMENTS)
        .values_list("id", flat=True)
    )
    by_python = {p.id for p in made if ledger._counts(p)}
    assert by_q == by_python
    assert by_python, "the predicate should accept something"


# --- per-line covered / uncovered amounts (task #443) -------------------


def test_statement_lines_expose_covered_and_uncovered(member):
    old = _charge(member, Charge.Category.TUITION, "2000", date(2024, 9, 1))
    new = _charge(member, Charge.Category.TUITION, "2000", date(2025, 9, 1))
    _pay(member, Payment.Type.TUITION, "2500", WHEN)

    acct = ledger.member_account(member)
    lines = {ln["obj"].id: ln for ln in acct["lines"] if ln["kind"] == "charge"}
    # Oldest-first: the first charge is fully covered, the second partly.
    assert lines[old.id]["covered"] == Decimal("2000")
    assert lines[old.id]["uncovered"] == Decimal("0")
    assert lines[new.id]["covered"] == Decimal("500")
    assert lines[new.id]["uncovered"] == Decimal("1500")
    assert acct["charge_covered"][new.id] == Decimal("500")


def test_waived_charge_has_no_covered_amount(member):
    c = _charge(member, Charge.Category.DUES, "100", date(2025, 9, 1),
                status=Charge.Status.WAIVED)
    acct = ledger.member_account(member)
    ln = next(ln for ln in acct["lines"] if ln["obj"].id == c.id)
    assert ln["covered"] is None
    assert ln["uncovered"] is None


# --- batched decision-exemption (task #443) -----------------------------


def test_decision_exempt_ids_matches_the_per_member_predicate(member):
    """``decision_exempt_ids`` is the batched form of
    ``tuition_decision_exempt`` — the treasurer Overview uses it instead of
    one member_account() per in-training member, so the two must agree."""
    # Exempt via enrollments: four non-skipping years, nothing paid.
    by_enrollment = User.objects.create_user(email="lg-enr@x.test", password="x")
    for year in (2021, 2022, 2023, 2024):
        TuitionEnrollment.objects.create(
            user=by_enrollment, tuition_period=_tuition_period(year, "2000"),
            status=TuitionEnrollment.Status.COMMITTED, source="staff")

    # Exempt via payment: four tuition years covered, no enrollment rows.
    by_payment = User.objects.create_user(email="lg-paid@x.test", password="x")
    for year in (2017, 2018, 2019, 2020):
        _charge(by_payment, Charge.Category.TUITION, "2000",
                date(year, 9, 1))
    _pay(by_payment, Payment.Type.TUITION, "8000", WHEN)

    # Not exempt: three non-skipping years plus a skipped one, unpaid.
    not_exempt = User.objects.create_user(email="lg-no@x.test", password="x")
    for year, status in ((2013, TuitionEnrollment.Status.COMMITTED),
                         (2014, TuitionEnrollment.Status.COMMITTED),
                         (2015, TuitionEnrollment.Status.COMMITTED),
                         (2016, TuitionEnrollment.Status.SKIPPING)):
        TuitionEnrollment.objects.create(
            user=not_exempt, tuition_period=_tuition_period(year, "2000"),
            status=status, source="staff")

    everyone = [member, by_enrollment, by_payment, not_exempt]
    batched = ledger.decision_exempt_ids()
    for u in everyone:
        assert (u.id in batched) == ledger.tuition_decision_exempt(u), u.email
    assert by_enrollment.id in batched
    assert by_payment.id in batched
    assert not_exempt.id not in batched


def test_voided_charge_within_the_cap_is_not_requirement_met(member):
    """A within-the-requirement year whose charge was voided must NOT read as
    "Requirement met" — that badge means *beyond* the four-year cap, and
    conflating the two made a treasurer-voided year look settled (task #655).
    """
    tp = _tuition_period(2024, "2000")
    TuitionEnrollment.objects.create(
        user=member, tuition_period=tp,
        status=TuitionEnrollment.Status.COMMITTED, source="staff")
    Charge.objects.filter(
        user=member, category=Charge.Category.TUITION, tuition_period=tp,
    ).update(status=Charge.Status.VOID, staff_adjusted=True)

    row = next(r for r in ledger.member_account(member)["tuition_rows"]
               if r["period"].slug == "t-2024")
    assert row["state"] == "no_charge"
    assert row["pct"] is None


def test_beyond_cap_year_still_reads_met_when_it_carries_a_charge(member):
    """The cap decides "met", but a live charge always wins over it — a fifth
    year that really was billed must show its own paid/unpaid state."""
    periods = [_tuition_period(2021 + i, "2000") for i in range(5)]
    for tp in periods:
        TuitionEnrollment.objects.create(
            user=member, tuition_period=tp,
            status=TuitionEnrollment.Status.COMMITTED, source="staff")
    _charge(member, Charge.Category.TUITION, "2000", date(2025, 9, 1),
            tuition_period=periods[4], staff_adjusted=True)

    by_slug = {r["period"].slug: r["state"]
               for r in ledger.member_account(member)["tuition_rows"]}
    assert by_slug["t-2025"] == "unpaid"
