"""Reconcile tab surfaces charge conflicts instead of clobbering (task #439)."""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import User
from payments.models import Charge, TuitionEnrollment, TuitionPeriod

pytestmark = pytest.mark.django_db


def test_reconcile_lists_staff_adjusted_conflict(client):
    staff = User.objects.create_user(email="tr4@x.test", password="x", is_staff=True)
    client.force_login(staff)
    TuitionPeriod.objects.all().delete()
    tp = TuitionPeriod.objects.create(
        name="AY 2026-2027 T", slug="t-2026", start_date=date(2026, 9, 1),
        end_date=date(2027, 8, 31), decision_due_date=date(2026, 8, 31),
        tuition_amount=Decimal("2000"))
    u = User.objects.create_user(email="cf@x.test", password="x")
    e = TuitionEnrollment.objects.create(
        user=u, tuition_period=tp, status=TuitionEnrollment.Status.COMMITTED,
        source="staff")
    c = Charge.objects.get(user=u)
    c.staff_adjusted = True
    c.save()
    e.status = TuitionEnrollment.Status.SKIPPING
    e.save()  # sync skips the staff-adjusted row → conflict
    resp = client.get(reverse("treasurer_reconcile"))
    assert resp.status_code == 200
    assert any(item["charge"] and item["charge"].id == c.id
               for item in resp.context["charge_conflicts"])
    assert b"cf@x.test" in resp.content or b"Charge conflicts" in resp.content
