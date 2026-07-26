"""audit_ledger — read-only parity report before the UI cutover (task #439)."""

from datetime import date, datetime
from datetime import timezone as tz
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from accounts.models import User
from payments.models import Charge, DuesPeriod, Payment

pytestmark = pytest.mark.django_db


def _run():
    out = StringIO()
    call_command("audit_ledger", stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_reports_owing_member_and_dues_disagreement():
    DuesPeriod.objects.all().delete()
    p = DuesPeriod.objects.create(
        name="AY 2024-2025", slug="ay-2024-2025",
        start_date=date(2024, 9, 1), due_date=date(2024, 9, 30),
        end_date=date(2025, 8, 31),
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"),
        dues_amount_analyst=Decimal("150"),
    )
    u = User.objects.create_user(email="au@x.test", password="x")
    Charge.objects.create(
        user=u, category=Charge.Category.DUES, amount=Decimal("100"),
        effective_date=p.start_date, dues_period=p)
    # Paid with dues money that carries no dues_period FK → the ledger's dues
    # bucket covers the charge, but the old FK-bound check can't see it →
    # disagreement. (Since #473 a *tuition* payment would no longer cover a
    # dues charge, so it can't produce this disagreement any more.)
    pay = Payment.objects.create(
        user=u, payment_type=Payment.Type.DUES, amount=Decimal("100"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE)
    Payment.objects.filter(pk=pay.pk).update(
        paid_at=datetime(2024, 10, 1, tzinfo=tz.utc))
    out = _run()
    assert "au@x.test" in out
    assert "disagree" in out.lower() or "covered by the ledger" in out.lower()


@pytest.mark.django_db
def test_clean_ledger_reports_no_disagreements():
    out = _run()
    assert "0 disagreement" in out.lower() or "no disagreement" in out.lower()
