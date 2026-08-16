from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from events.models import Event
from payments.models import TuitionEnrollment, TuitionPeriod
from registrations.views import _find_covered_tier, _tuition_block_reason

User = get_user_model()


@pytest.fixture
def periods(db):
    TuitionPeriod.objects.all().delete()  # seed migration pre-populates periods

    def mk(y):
        return TuitionPeriod.objects.create(
            name=f"AY {y}–{y+1}", slug=f"t{y}", start_date=date(y, 9, 1),
            decision_due_date=date(y, 10, 31), end_date=date(y + 1, 8, 31),
            tuition_amount=Decimal("2500"),
        )

    return mk(2025), mk(2026)


@pytest.fixture
def student(db):
    u = User.objects.create_user(email="s2@example.com", password="x")
    u.profile.role = "candidate"
    u.profile.save(update_fields=["role"])
    return u


@pytest.mark.django_db
def test_gate_demands_the_events_ay_decision(periods, student):
    p25, p26 = periods
    TuitionEnrollment.objects.create(
        user=student, tuition_period=p25,
        status=TuitionEnrollment.Status.PAID_IN_FULL,
    )
    event = Event.objects.create(
        title="Fall", slug="fall", start_date=date(2026, 9, 15),
        end_date=date(2027, 6, 1),
    )
    reason = _tuition_block_reason(student, event)
    assert reason is not None and "2026–2027" in reason

    TuitionEnrollment.objects.create(
        user=student, tuition_period=p26,
        status=TuitionEnrollment.Status.SKIPPING,
    )
    assert _tuition_block_reason(student, event) is None


@pytest.mark.django_db
def test_coverage_requires_the_events_ay(periods, student):
    from events.models import Audience, PriceTier

    p25, p26 = periods
    TuitionEnrollment.objects.create(
        user=student, tuition_period=p25,
        status=TuitionEnrollment.Status.PAID_IN_FULL,
    )
    event = Event.objects.create(
        title="Fall2", slug="fall2", start_date=date(2026, 9, 15),
        end_date=date(2027, 6, 1),
    )
    PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("200"),
        covered_by_tuition=True,
    )
    assert _find_covered_tier(student, event) is None

    TuitionEnrollment.objects.create(
        user=student, tuition_period=p26,
        status=TuitionEnrollment.Status.PAID_IN_FULL,
    )
    assert _find_covered_tier(student, event) is not None


@pytest.mark.django_db
def test_plan_requested_is_covered(periods, student):
    """A PLAN_REQUESTED enrollment (awaiting the Board's decision on a payment
    plan) has a decision on file, so it clears the broad gate — and since task
    #484 it also covers events, exactly as COMMITTED does. The Board's approval
    sets the installment schedule; it no longer gates registration."""
    from events.models import Audience, PriceTier

    p25, p26 = periods
    TuitionEnrollment.objects.create(
        user=student, tuition_period=p26,
        status=TuitionEnrollment.Status.PLAN_REQUESTED,
    )
    event = Event.objects.create(
        title="Plain Seminar", slug="plain-seminar",
        start_date=date(2026, 9, 15), end_date=date(2027, 6, 1),
    )
    assert event.event_type == Event.Type.SEMINAR
    PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("200"),
        covered_by_tuition=True,
    )

    assert _tuition_block_reason(student, event) is None
    assert _find_covered_tier(student, event) is not None


@pytest.mark.django_db
def test_blocked_page_links_to_that_years_decision_form(client, periods, student):
    """The block names the event's academic year, so its link must land on
    that year's form. A member joining for the new year met two identical
    decision forms and filled the wrong one (task #599)."""
    from django.urls import reverse

    _p25, p26 = periods
    event = Event.objects.create(
        title="Fall3", slug="fall3", start_date=date(2026, 9, 15),
        end_date=date(2027, 6, 1), status=Event.Status.OPEN, published=True,
    )
    client.force_login(student)
    resp = client.get(reverse("registrations:register", args=[event.slug]))

    assert resp.status_code == 403
    assert f"#decision-{p26.slug}" in resp.content.decode()
