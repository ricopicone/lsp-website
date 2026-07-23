from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from payments.models import TuitionEnrollment, TuitionPeriod

User = get_user_model()


@pytest.mark.django_db
def test_member_can_record_upcoming_year_decision(client):
    # Periods: one containing today, one future.
    import datetime
    today = datetime.date.today()
    cur = TuitionPeriod.objects.create(
        name="Cur", slug="cur", start_date=today.replace(month=1, day=1),
        decision_due_date=today, end_date=today.replace(month=12, day=31),
        tuition_amount=Decimal("2500"),
    )
    nxt = TuitionPeriod.objects.create(
        name="Next", slug="next",
        start_date=today.replace(year=today.year + 1, month=1, day=1),
        decision_due_date=today.replace(year=today.year + 1),
        end_date=today.replace(year=today.year + 1, month=12, day=31),
        tuition_amount=Decimal("2500"),
    )
    u = User.objects.create_user(email="d@example.com", password="x")
    u.profile.role = "candidate"
    u.profile.save(update_fields=["role"])
    client.force_login(u)

    client.post(reverse("tuition"), {"status": "skipping", "period": "next"})
    assert TuitionEnrollment.objects.filter(user=u, tuition_period=nxt).exists()
    assert not TuitionEnrollment.objects.filter(user=u, tuition_period=cur).exists()
