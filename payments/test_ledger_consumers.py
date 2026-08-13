"""Banner + reminders + Money tab read the unified ledger (task #439)."""

from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from payments.models import Charge, DuesPeriod, Payment

pytestmark = pytest.mark.django_db


def _current_dues_period():
    DuesPeriod.objects.all().delete()
    today = timezone.localdate()
    start = today.year if today.month >= 9 else today.year - 1
    return DuesPeriod.objects.create(
        name=f"AY {start}-{start + 1}", slug=f"ay-{start}-{start + 1}",
        start_date=date(start, 9, 1),
        due_date=today - timedelta(days=1),   # past due → reminders fire
        end_date=date(start + 1, 8, 31),
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"),
        dues_amount_analyst=Decimal("150"))


def _member(email, role="candidate"):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = role
    u.profile.save()
    return u


def test_landing_banner_shows_outstanding_balance(client):
    p = _current_dues_period()
    u = _member("bn@x.test")
    Charge.objects.create(user=u, category=Charge.Category.DUES,
                          amount=Decimal("100"), effective_date=p.start_date,
                          dues_period=p)
    client.force_login(u)
    resp = client.get(reverse("core:landing"))
    assert resp.context["outstanding_balance"] == Decimal("100")


def test_landing_banner_absent_when_square(client):
    _current_dues_period()
    u = _member("sq@x.test")
    client.force_login(u)
    resp = client.get(reverse("core:landing"))
    assert not resp.context.get("outstanding_balance")


def test_dues_reminder_skips_ledger_covered_member():
    """Coverage, not the FK, decides: dues money with no ``dues_period`` FK
    still settles the dues charge, so no reminder goes out."""
    p = _current_dues_period()
    covered = _member("cov@x.test")
    Charge.objects.create(user=covered, category=Charge.Category.DUES,
                          amount=Decimal("100"), effective_date=p.start_date,
                          dues_period=p)
    pay = Payment.objects.create(
        user=covered, payment_type=Payment.Type.DUES, amount=Decimal("100"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE)
    Payment.objects.filter(pk=pay.pk).update(paid_at=timezone.now())
    unpaid = _member("unp@x.test")
    Charge.objects.create(user=unpaid, category=Charge.Category.DUES,
                          amount=Decimal("100"), effective_date=p.start_date,
                          dues_period=p)
    out = StringIO()
    call_command("send_dues_reminders", "--dry-run", stdout=out)
    text = out.getvalue()
    assert "unp@x.test" in text
    assert "cov@x.test" not in text


def test_dues_reminder_not_silenced_by_tuition_money():
    """Task #473: dues accounting is dues-only. Tuition money sitting on the
    account does not settle a dues charge, so the member is still reminded —
    the fix is for the treasurer to re-categorize the payment, not for dues to
    quietly read as paid."""
    p = _current_dues_period()
    u = _member("tuit@x.test")
    Charge.objects.create(user=u, category=Charge.Category.DUES,
                          amount=Decimal("100"), effective_date=p.start_date,
                          dues_period=p)
    pay = Payment.objects.create(
        user=u, payment_type=Payment.Type.TUITION, amount=Decimal("100"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE)
    Payment.objects.filter(pk=pay.pk).update(paid_at=timezone.now())
    out = StringIO()
    call_command("send_dues_reminders", "--dry-run", stdout=out)
    assert "tuit@x.test" in out.getvalue()


def test_user_paid_for_period_is_gone():
    import payments.dues as dues
    assert not hasattr(dues, "user_paid_for_period")
