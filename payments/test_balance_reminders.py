"""Weekly outstanding-balance reminders (task #450 phase D).

The balance in the email/bell/row must be the exact number the treasurer's
Accounts view shows as "Owing" — computed by ``payments.ledger`` and never
reimplemented here.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone

from payments import ledger
from payments.management.commands import send_balance_reminders
from payments.models import (
    BalanceReminder,
    Charge,
    DuesPeriod,
    TuitionEnrollment,
    TuitionInstallment,
    TuitionPeriod,
)

User = get_user_model()

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_periods():
    DuesPeriod.objects.all().delete()
    TuitionPeriod.objects.all().delete()


@pytest.fixture
def period():
    return DuesPeriod.objects.create(
        name="AY 2026-2027", slug="ay-2026-2027",
        start_date=date(2026, 9, 1), due_date=date(2026, 9, 30),
        end_date=date(2027, 8, 31),
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"),
        dues_amount_analyst=Decimal("150"),
    )


@pytest.fixture
def tuition_period():
    return TuitionPeriod.objects.create(
        name="AY 2026-2027 Tuition", slug="ay-2026-2027-tuition",
        start_date=date(2026, 9, 1), decision_due_date=date(2026, 9, 1),
        end_date=date(2027, 8, 31), tuition_amount=Decimal("5000"),
    )


@pytest.fixture
def member():
    u = User.objects.create_user(email="owes@example.com", password="x")
    u.profile.role = "candidate"
    u.profile.save(update_fields=["role"])
    return u


def _charge(user, amount, eff=date(2026, 9, 1), category=Charge.Category.DUES, **kw):
    return Charge.objects.create(
        user=user, category=category, amount=Decimal(amount),
        effective_date=eff, **kw,
    )


def _freeze(monkeypatch, iso_date):
    """Patch timezone.now() in the command module to noon on ``iso_date``.

    freezegun isn't a project dependency, so the command's own
    ``timezone.now`` reference is monkeypatched directly (it reads
    ``timezone.now().date()``), mirroring test_tuition_reminder_dates.py.
    """
    frozen = timezone.make_aware(
        datetime.combine(date.fromisoformat(iso_date), datetime.min.time())
    )
    monkeypatch.setattr(send_balance_reminders.timezone, "now", lambda: frozen)


@pytest.mark.django_db
def test_nothing_before_due_date(period, member, mailoutbox, settings, monkeypatch):
    settings.EMAIL_MAX_SEND_RATE = 1000.0
    _charge(member, "100")
    _freeze(monkeypatch, "2026-09-15")
    call_command("send_balance_reminders")
    assert len(mailoutbox) == 0
    assert BalanceReminder.objects.count() == 0


@pytest.mark.django_db
def test_positive_balance_member_reminded_after_due_date(
    period, member, mailoutbox, settings, monkeypatch,
):
    settings.EMAIL_MAX_SEND_RATE = 1000.0
    _charge(member, "100")
    _freeze(monkeypatch, "2026-10-01")
    call_command("send_balance_reminders")

    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == [member.email]
    assert "100" in mailoutbox[0].body

    reminder = BalanceReminder.objects.get(user=member)
    assert reminder.balance == Decimal("100.00")


@pytest.mark.django_db
def test_zero_balance_member_not_reminded(period, member, mailoutbox, settings, monkeypatch):
    settings.EMAIL_MAX_SEND_RATE = 1000.0
    # No charges at all → balance is 0, nothing to chase.
    _freeze(monkeypatch, "2026-10-01")
    call_command("send_balance_reminders")
    assert len(mailoutbox) == 0
    assert BalanceReminder.objects.count() == 0


@pytest.mark.django_db
def test_second_run_within_seven_days_is_silent(
    period, member, mailoutbox, settings, monkeypatch,
):
    settings.EMAIL_MAX_SEND_RATE = 1000.0
    _charge(member, "100")
    _freeze(monkeypatch, "2026-10-01")
    call_command("send_balance_reminders")
    assert len(mailoutbox) == 1

    _freeze(monkeypatch, "2026-10-05")  # 4 days later, inside the 7-day window
    call_command("send_balance_reminders")
    assert len(mailoutbox) == 1  # unchanged — no second send
    assert BalanceReminder.objects.filter(user=member).count() == 1


@pytest.mark.django_db
def test_run_after_seven_days_sends_again(
    period, member, mailoutbox, settings, monkeypatch,
):
    settings.EMAIL_MAX_SEND_RATE = 1000.0
    _charge(member, "100")
    _freeze(monkeypatch, "2026-10-01")
    call_command("send_balance_reminders")
    assert len(mailoutbox) == 1

    _freeze(monkeypatch, "2026-10-09")  # 8 days later, outside the window
    call_command("send_balance_reminders")
    assert len(mailoutbox) == 2
    assert BalanceReminder.objects.filter(user=member).count() == 2


@pytest.mark.django_db
def test_persona_skipped(period, member, mailoutbox, settings, monkeypatch):
    settings.EMAIL_MAX_SEND_RATE = 1000.0
    member.profile.is_persona = True
    member.profile.save(update_fields=["is_persona"])
    _charge(member, "100")
    _freeze(monkeypatch, "2026-10-01")
    call_command("send_balance_reminders")
    assert len(mailoutbox) == 0
    assert BalanceReminder.objects.count() == 0


@pytest.mark.django_db
def test_inactive_user_skipped(period, member, mailoutbox, settings, monkeypatch):
    settings.EMAIL_MAX_SEND_RATE = 1000.0
    member.is_active = False
    member.save(update_fields=["is_active"])
    _charge(member, "100")
    _freeze(monkeypatch, "2026-10-01")
    call_command("send_balance_reminders")
    assert len(mailoutbox) == 0
    assert BalanceReminder.objects.count() == 0


@pytest.mark.django_db
def test_balance_matches_treasurer_accounts_view(period, member, settings, monkeypatch):
    """The reminder's balance must equal accounts_overview()'s "owes" figure
    for a member with one unpaid charge — same helper, no reimplementation."""
    settings.EMAIL_MAX_SEND_RATE = 1000.0
    _charge(member, "150")
    _freeze(monkeypatch, "2026-10-01")
    call_command("send_balance_reminders")

    overview_row = next(
        r for r in ledger.accounts_overview() if r["user"].id == member.id
    )
    reminder = BalanceReminder.objects.get(user=member)
    assert reminder.balance == overview_row["owes"] == Decimal("150.00")


@pytest.mark.django_db
def test_plan_requested_member_not_reminded(
    period, tuition_period, member, mailoutbox, settings, monkeypatch,
):
    """A member whose payment-plan request is pending with the Board isn't
    dunned on the balance while the request is under review."""
    settings.EMAIL_MAX_SEND_RATE = 1000.0
    _charge(member, "100")
    TuitionEnrollment.objects.create(
        user=member, tuition_period=tuition_period,
        status=TuitionEnrollment.Status.PLAN_REQUESTED,
    )
    _freeze(monkeypatch, "2026-10-01")
    call_command("send_balance_reminders")
    assert len(mailoutbox) == 0
    assert BalanceReminder.objects.count() == 0


@pytest.mark.django_db
def test_payment_plan_current_member_not_reminded(
    period, tuition_period, member, mailoutbox, settings, monkeypatch,
):
    """A member on an approved payment plan with no overdue installment is
    current — no balance reminder, even though the ledger balance is > 0."""
    settings.EMAIL_MAX_SEND_RATE = 1000.0
    _charge(member, "100")
    enrollment = TuitionEnrollment.objects.create(
        user=member, tuition_period=tuition_period,
        status=TuitionEnrollment.Status.PAYMENT_PLAN,
    )
    TuitionInstallment.objects.create(
        enrollment=enrollment, sequence=1,
        due_date=date(2026, 12, 1), amount=Decimal("100"), paid=False,
    )
    _freeze(monkeypatch, "2026-10-01")
    call_command("send_balance_reminders")
    assert len(mailoutbox) == 0
    assert BalanceReminder.objects.count() == 0


@pytest.mark.django_db
def test_payment_plan_overdue_installment_still_reminded(
    period, tuition_period, member, mailoutbox, settings, monkeypatch,
):
    """An overdue unpaid installment on a payment plan still triggers the
    balance reminder — the plan has lapsed into arrears."""
    settings.EMAIL_MAX_SEND_RATE = 1000.0
    _charge(member, "100")
    enrollment = TuitionEnrollment.objects.create(
        user=member, tuition_period=tuition_period,
        status=TuitionEnrollment.Status.PAYMENT_PLAN,
    )
    TuitionInstallment.objects.create(
        enrollment=enrollment, sequence=1,
        due_date=date(2026, 9, 1), amount=Decimal("100"), paid=False,
    )
    _freeze(monkeypatch, "2026-10-01")
    call_command("send_balance_reminders")
    assert len(mailoutbox) == 1
    assert BalanceReminder.objects.count() == 1
