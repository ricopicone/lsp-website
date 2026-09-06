"""Payment-plan members get nudged on their installment due dates (task #494).

Before this, ``send_tuition_reminders`` only fired once an installment was
already *past* due, and the email said nothing about which installment or how
much — it fell through to a generic "Your current tuition decision is:
Payment plan".
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone

from payments.management.commands import send_tuition_reminders
from payments.models import TuitionEnrollment, TuitionInstallment, TuitionPeriod
from payments.testing import make_period

User = get_user_model()


@pytest.fixture
def period(db):
    return make_period(TuitionPeriod, 
        name="AY 2026–2027", slug="ay-2026-2027-tuition",
        start_date=date(2026, 9, 1), decision_due_date=date(2026, 10, 31),
        payment_due_date=date(2026, 11, 30), end_date=date(2027, 8, 31),
        tuition_amount=Decimal("2700"),
    )


@pytest.fixture
def student(db):
    u = User.objects.create_user(email="plan@example.com", password="x")
    u.profile.role = "pre_candidate"
    u.profile.save(update_fields=["role"])
    return u


@pytest.fixture
def enrollment(period, student):
    return TuitionEnrollment.objects.create(
        user=student, tuition_period=period,
        status=TuitionEnrollment.Status.PAYMENT_PLAN,
    )


def _installment(enrollment, sequence, due_date, *, paid=False, amount="300"):
    return TuitionInstallment.objects.create(
        enrollment=enrollment, sequence=sequence, due_date=due_date,
        amount=Decimal(amount), paid=paid,
    )


def _freeze(monkeypatch, iso_date):
    """Patch timezone.now() in the command module (freezegun isn't a dep)."""
    frozen = timezone.make_aware(
        datetime.combine(date.fromisoformat(iso_date), datetime.min.time())
    )
    monkeypatch.setattr(send_tuition_reminders.timezone, "now", lambda: frozen)


@pytest.mark.django_db
def test_an_upcoming_installment_is_nudged_before_it_is_late(
    enrollment, mailoutbox, settings, monkeypatch,
):
    settings.EMAIL_MAX_SEND_RATE = 1000.0
    _installment(enrollment, 1, date(2026, 11, 20))  # 5 days out
    _freeze(monkeypatch, "2026-11-15")

    call_command("send_tuition_reminders")

    assert len(mailoutbox) == 1


@pytest.mark.django_db
def test_an_installment_beyond_the_lead_window_is_left_alone(
    enrollment, mailoutbox, settings, monkeypatch,
):
    settings.EMAIL_MAX_SEND_RATE = 1000.0
    _installment(enrollment, 1, date(2026, 12, 20))
    _freeze(monkeypatch, "2026-11-15")

    call_command("send_tuition_reminders")

    assert mailoutbox == []


@pytest.mark.django_db
def test_the_nudge_names_the_installment_amount_and_due_date(
    enrollment, mailoutbox, settings, monkeypatch,
):
    settings.EMAIL_MAX_SEND_RATE = 1000.0
    _installment(enrollment, 1, date(2026, 11, 20), amount="300")
    _installment(enrollment, 2, date(2027, 2, 1), amount="300")
    _freeze(monkeypatch, "2026-11-15")

    call_command("send_tuition_reminders")

    body = mailoutbox[0].body
    assert "$300.00" in body
    assert "November 20, 2026" in body
    assert "1 of 2" in body


@pytest.mark.django_db
def test_an_overdue_nudge_says_it_was_due(
    enrollment, mailoutbox, settings, monkeypatch,
):
    settings.EMAIL_MAX_SEND_RATE = 1000.0
    _installment(enrollment, 1, date(2026, 10, 1))
    _freeze(monkeypatch, "2026-11-15")

    call_command("send_tuition_reminders")

    body = mailoutbox[0].body
    assert "was due" in body
    assert "October 1, 2026" in body


@pytest.mark.django_db
def test_a_paid_up_plan_is_not_nudged(
    enrollment, mailoutbox, settings, monkeypatch,
):
    settings.EMAIL_MAX_SEND_RATE = 1000.0
    _installment(enrollment, 1, date(2026, 10, 1), paid=True)
    _installment(enrollment, 2, date(2027, 2, 1))
    _freeze(monkeypatch, "2026-11-15")

    call_command("send_tuition_reminders")

    assert mailoutbox == []
