"""Committed-unpaid tuition reminders wait for payment_due_date."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone

from payments.management.commands import send_tuition_reminders
from payments.models import TuitionEnrollment, TuitionPeriod

User = get_user_model()


@pytest.fixture
def period(db):
    return TuitionPeriod.objects.create(
        name="AY 2026–2027", slug="ay-2026-2027-tuition",
        start_date=date(2026, 9, 1), decision_due_date=date(2026, 10, 31),
        payment_due_date=date(2026, 11, 30), end_date=date(2027, 8, 31),
        tuition_amount=Decimal("2500"),
    )


@pytest.fixture
def student(db):
    u = User.objects.create_user(email="s@example.com", password="x")
    u.profile.role = "pre_candidate"
    u.profile.save(update_fields=["role"])
    return u


def _freeze(monkeypatch, iso_date):
    """Patch timezone.now() in the command module to noon on ``iso_date``.

    freezegun isn't a project dependency, so the command's own
    ``timezone.now`` reference is monkeypatched directly (it reads
    ``timezone.localdate()``).
    """
    frozen = timezone.make_aware(
        datetime.combine(date.fromisoformat(iso_date), datetime.min.time())
    )
    monkeypatch.setattr(send_tuition_reminders.timezone, "now", lambda: frozen)


@pytest.mark.django_db
def test_committed_not_reminded_before_payment_due(
    period, student, mailoutbox, settings, monkeypatch,
):
    settings.EMAIL_MAX_SEND_RATE = 1000.0
    TuitionEnrollment.objects.create(
        user=student, tuition_period=period,
        status=TuitionEnrollment.Status.COMMITTED,
    )
    _freeze(monkeypatch, "2026-11-15")
    call_command("send_tuition_reminders")
    assert len(mailoutbox) == 0


@pytest.mark.django_db
def test_committed_reminded_after_payment_due(
    period, student, mailoutbox, settings, monkeypatch,
):
    settings.EMAIL_MAX_SEND_RATE = 1000.0
    TuitionEnrollment.objects.create(
        user=student, tuition_period=period,
        status=TuitionEnrollment.Status.COMMITTED,
    )
    _freeze(monkeypatch, "2026-12-01")
    call_command("send_tuition_reminders")
    assert len(mailoutbox) == 1


@pytest.mark.django_db
def test_undecided_reminded_after_decision_due(
    period, student, mailoutbox, settings, monkeypatch,
):
    settings.EMAIL_MAX_SEND_RATE = 1000.0
    _freeze(monkeypatch, "2026-11-15")
    call_command("send_tuition_reminders")
    assert len(mailoutbox) == 1
