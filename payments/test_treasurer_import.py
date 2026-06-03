"""Tests for the treasurer ledger importer (name matching + import command)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from io import StringIO

import openpyxl
import pytest
from django.core.management import call_command

from accounts.models import User
from payments.models import (
    DuesPeriod,
    Payment,
    TuitionEnrollment,
    TuitionInstallment,
    TuitionPeriod,
)
from payments.treasurer_import import (
    NameMatcher,
    clean_raw_name,
    name_tokens,
    parse_dues_ledger,
    parse_tuition_ledger,
)

# ---------------------------------------------------------------------------
# Name matching
# ---------------------------------------------------------------------------

ROSTER = [
    (1, "Garret", "Barnwell", ""),
    (2, "Julien", "Fischer", ""),
    (3, "Laura", "Rivera Rodriguez", ""),
    (4, "Shanna", "Carlson de la Torre", "Shanna Carlson"),
    (5, "Doreen Xuekang", "Deng", ""),
    (6, "María", "Líza Ahearne", ""),
    (7, "Tod", "Edgerton", ""),          # prod stores the short form
    (8, "Christopher", "Chamberlin", ""),
    (9, "Christopher", "Scott", ""),
    (10, "Christopher", "Bell", ""),
    (11, "Apurva Kiran", "Shah", ""),    # for the subset rule (no alias involved)
]


@pytest.fixture
def matcher():
    return NameMatcher(ROSTER)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Garret Barnwell", 1),
        ("Garet Barnwell", 1),           # typo -> last+initial
        ("Julien Fischer", 2),
        ("Julein Fischer", 2),           # typo
        ("Laura Rodriguez", 3),          # partial surname
        ("Laura Rivera Rodriguez", 3),
        ("Shanna Carlson de la Torre", 4),
        ("Shanna Carlson", 4),           # display_name + particle drop
        ("Deng Xuekang", 5),             # reordered, partial
        ("Doreen Xuekang Deng", 5),
        ("María Líza Ahearne", 6),       # accents
        ("Maria Liza Ahearne", 6),
        ("Tod Edgerton", 7),             # exact (prod short form)
        ("Michael Tod Edgerton", 7),     # verified alias -> "Tod Edgerton"
        ("Christopher Chamberlin", 8),   # exact among several Christophers
        ("Christopher Chamberlain", 8),  # verified alias (ledger typo)
        ("Christopher Scott", 9),
        ("Kiran Shah", 11),              # middle name stands in for first -> subset
        ("Shanna Carlson PhD", 4),       # professional credential dropped
        ("Garret Barnwell LMFT", 1),     # credential dropped
        ("Christopher Scott LCSW", 9),   # credential dropped
        ("Julien Fischer, PsyD", 2),     # credential + punctuation dropped
    ],
)
def test_high_confidence_matches(matcher, raw, expected):
    assert matcher.match(raw).user_id == expected


def test_unmapped_surname_typo_not_matched(matcher):
    # A surname typo that is NOT in the verified alias map must not match — we
    # never fuzzy-guess surnames. (Chamberlin is several Christophers, so a bare
    # "Christopher" can't disambiguate either.)
    assert matcher.match("Christopher Chamberlane").user_id is None
    assert matcher.match("Christopher").user_id is None


def test_ambiguous_first_name_not_matched(matcher):
    # Multiple Christophers, no surname -> must not guess.
    assert matcher.match("Christopher").user_id is None


def test_third_party_payer_uses_member(matcher):
    assert matcher.match("Garret Barnwell (Payment from someone else)").user_id == 1


def test_unknown_name_returns_none(matcher):
    assert matcher.match("Someone Entirely Unknown").user_id is None


def test_verified_alias_resolves_to_canonical():
    # "Wu Bing" / "Wu Bing (Winnie)" both alias to the roster's "Winnie Wu".
    people = [(1, "Winnie", "Wu", ""), (2, "Alice Wei", "Wu", "")]
    m = NameMatcher(people)
    assert m.match("Wu Bing").user_id == 1
    assert m.match("Wu Bing (Winnie)").user_id == 1
    res = m.match("Wu Bing")
    assert res.confidence == "alias"


def test_alias_target_missing_from_roster_is_unmatched():
    # If the canonical target isn't in the roster, the alias must not silently
    # match the wrong person — it returns None with a clear reason.
    m = NameMatcher([(1, "Someone", "Else", "")])
    res = m.match("Roberto Lascano")  # aliases to "Roberto Lazcano", absent here
    assert res.user_id is None
    assert "alias target" in res.reason


def test_clean_raw_name():
    assert clean_raw_name("Chan Wai Lim (William Chan)") == "Chan Wai Lim"
    assert clean_raw_name("Alice Wu (Payment from Joseph)") == "Alice Wu"
    assert clean_raw_name("Marshall Meyer / Tyshira Dingle") == "Marshall Meyer"


def test_name_tokens_drops_honorifics():
    assert name_tokens("Dr. Robert Beshara Jr.") == ["robert", "beshara"]


def test_name_tokens_drops_credentials_but_keeps_real_surnames():
    assert name_tokens("Annie G Rogers PhD") == ["annie", "g", "rogers"]
    assert name_tokens("Nathan Lupo LMFT") == ["nathan", "lupo"]
    # "Ma" is a surname, not the MA degree — must survive.
    assert name_tokens("Karen Ma") == ["karen", "ma"]


# ---------------------------------------------------------------------------
# Ledger parsing + import command
# ---------------------------------------------------------------------------


def _write_tuition_xlsx(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Name", "Amount", "Date", "Payment", "Paid as (If Different)"])
    ws.append(["Garret Barnwell", 500, datetime(2024, 7, 17), "1st", None])
    ws.append(["Garret Barnwell", 1500, datetime(2024, 11, 7), "2nd, Full", None])
    ws.append(["Julien Fischer", 2000, datetime(2024, 11, 4), "Full", None])
    ws.append(["Laura Rodriguez", 200, datetime(2024, 10, 1), "1st", None])
    ws.append(["Unknown Person", 2000, datetime(2024, 10, 1), "Full", None])
    ws.append([None, None, None, None, None])  # blank row
    wb.save(path)


def _write_dues_xlsx(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Garret Barnwell", 100, "Stripe", datetime(2024, 7, 17)])
    ws.append(["Julien Fischer", 100, "Paypal", datetime(2024, 11, 4)])
    ws.append(["Julien Fischer", 1000, datetime(2024, 11, 4), "DONATION"])
    ws.append([None, None, 1200])  # total row, no name
    wb.save(path)


@pytest.fixture
def source_dir(tmp_path):
    _write_tuition_xlsx(tmp_path / "Tuition 24-25.xlsx")
    (tmp_path / "Treasurer 2026").mkdir()
    _write_dues_xlsx(tmp_path / "Dues 24-25.xlsx")
    return tmp_path


@pytest.fixture
def roster_db(db):
    def mk(uid, first, last):
        u = User.objects.create_user(email=f"u{uid}@x.test", password="x")
        u.first_name, u.last_name = first, last
        u.save()
        return u

    return {
        1: mk(1, "Garret", "Barnwell"),
        2: mk(2, "Julien", "Fischer"),
        3: mk(3, "Laura", "Rivera Rodriguez"),
    }


def test_parse_tuition_ledger(source_dir):
    rows = parse_tuition_ledger(source_dir / "Tuition 24-25.xlsx")
    assert [r.raw_name for r in rows] == [
        "Garret Barnwell", "Garret Barnwell", "Julien Fischer",
        "Laura Rodriguez", "Unknown Person",
    ]
    assert rows[0].amount == Decimal("500")
    assert rows[0].installment_label == "1st"
    assert rows[0].paid_on == date(2024, 7, 17)


def test_parse_dues_ledger_sniffs_method_and_donation(source_dir):
    rows = parse_dues_ledger(source_dir / "Dues 24-25.xlsx")
    assert len(rows) == 3  # total row dropped
    assert rows[0].method == "Stripe"
    assert rows[0].paid_on == date(2024, 7, 17)
    assert rows[1].method == "Paypal"
    assert "donation" in rows[2].flags


def test_dry_run_writes_nothing(source_dir, roster_db):
    out = StringIO()
    call_command("import_treasurer_payments", "--source-dir", str(source_dir),
                 "--datasets", "tuition-24-25", stdout=out)
    assert Payment.objects.count() == 0
    # Seed migrations may create a current-AY period; assert our dataset's
    # period was not created by the dry-run.
    assert not TuitionPeriod.objects.filter(slug="ay-2024-2025-tuition").exists()
    assert "DRY-RUN" in out.getvalue()


def test_commit_tuition_builds_payments_installments_enrollments(source_dir, roster_db):
    call_command("import_treasurer_payments", "--source-dir", str(source_dir),
                 "--datasets", "tuition-24-25", "--commit", stdout=StringIO())

    # Unknown Person is unmatched -> not imported.
    assert Payment.objects.filter(payment_type=Payment.Type.TUITION).count() == 4
    period = TuitionPeriod.objects.get(slug="ay-2024-2025-tuition")
    assert period.tuition_amount == Decimal("2000")

    barnwell = roster_db[1]
    enr = TuitionEnrollment.objects.get(user=barnwell, tuition_period=period)
    # 500 + 1500 = 2000 == full -> PAID_IN_FULL
    assert enr.status == TuitionEnrollment.Status.PAID_IN_FULL
    assert enr.installments.count() == 2
    assert set(enr.installments.values_list("sequence", flat=True)) == {1, 2}

    laura = roster_db[3]
    enr_l = TuitionEnrollment.objects.get(user=laura, tuition_period=period)
    # 200 < 2000 -> PAYMENT_PLAN
    assert enr_l.status == TuitionEnrollment.Status.PAYMENT_PLAN

    # Each payment links its installment and is SUCCEEDED, tagged imported.
    from accounts.models import Source
    assert enr.source == Source.IMPORTED
    for p in Payment.objects.filter(user=barnwell):
        assert p.status == Payment.Status.SUCCEEDED
        assert p.tuition_installment is not None
        assert p.paid_at is not None
        assert p.source == Source.IMPORTED


def test_commit_is_idempotent(source_dir, roster_db):
    args = ("--source-dir", str(source_dir), "--datasets", "tuition-24-25", "--commit")
    call_command("import_treasurer_payments", *args, stdout=StringIO())
    n_pay = Payment.objects.count()
    n_inst = TuitionInstallment.objects.count()
    call_command("import_treasurer_payments", *args, stdout=StringIO())
    assert Payment.objects.count() == n_pay
    assert TuitionInstallment.objects.count() == n_inst


def test_reconciles_preexisting_period_amount(source_dir, roster_db):
    # A period created ahead of time (e.g. by the cron, inheriting the prior
    # year's amount) gets its tuition_amount corrected to the ledger's value.
    from datetime import date as _date
    TuitionPeriod.objects.create(
        name="AY 2024–2025", slug="ay-2024-2025-tuition",
        start_date=_date(2024, 9, 1), decision_due_date=_date(2024, 8, 31),
        end_date=_date(2025, 8, 31), tuition_amount=Decimal("999"),
    )
    call_command("import_treasurer_payments", "--source-dir", str(source_dir),
                 "--datasets", "tuition-24-25", "--commit", stdout=StringIO())
    period = TuitionPeriod.objects.get(slug="ay-2024-2025-tuition")
    assert period.tuition_amount == Decimal("2000")


def test_commit_dues_and_donation(source_dir, roster_db):
    call_command("import_treasurer_payments", "--source-dir", str(source_dir),
                 "--datasets", "dues-24-25", "--commit", stdout=StringIO())
    dues = Payment.objects.filter(payment_type=Payment.Type.DUES)
    donations = Payment.objects.filter(payment_type=Payment.Type.DONATION)
    assert dues.count() == 2
    assert donations.count() == 1
    period = DuesPeriod.objects.get(slug="ay-2024-2025")
    assert all(p.dues_period_id == period.id for p in dues)
    assert donations.first().dues_period_id is None
    # Stripe -> STRIPE, Paypal -> OFFLINE with note
    stripe_pay = dues.get(user=roster_db[1])
    assert stripe_pay.method == Payment.Method.STRIPE
    paypal_pay = dues.get(user=roster_db[2])
    assert paypal_pay.method == Payment.Method.OFFLINE
    assert "Paypal" in paypal_pay.notes


def test_unmatched_names_reported(source_dir, roster_db):
    out = StringIO()
    call_command("import_treasurer_payments", "--source-dir", str(source_dir),
                 "--datasets", "tuition-24-25", "--commit", stdout=out)
    assert "Unknown Person" in out.getvalue()
    assert "UNMATCHED" in out.getvalue()
