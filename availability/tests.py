"""Tests for the analyst-availability data model and services (Phase 1)."""

from __future__ import annotations

import datetime as _dt

import pytest
from django.db import IntegrityError

from accounts.models import Profile, User

from . import services
from .models import AnalystFunction, AvailabilitySpan

pytestmark = pytest.mark.django_db

Status = AvailabilitySpan.Status


# ---- Fixtures ------------------------------------------------------------


@pytest.fixture
def analyst():
    user = User.objects.create_user(
        email="analyst@example.com", password="pw",
        first_name="Anna", last_name="Analyst",
    )
    profile = user.profile
    profile.role = Profile.Role.ANALYST
    profile.save()
    return profile


@pytest.fixture
def interviews():
    return AnalystFunction.objects.get(slug="application-interviews")


# ---- Seed migration ------------------------------------------------------


def test_four_functions_seeded():
    slugs = list(
        AnalystFunction.objects.order_by("display_order").values_list("slug", flat=True)
    )
    assert slugs == [
        "application-interviews",
        "advisor",
        "control-analysis",
        "personal-analysis",
    ]


def test_column_label_falls_back_to_name(interviews):
    assert interviews.column_label == "Application Interviews"
    interviews.short_label = "Interviews"
    assert interviews.column_label == "Interviews"


# ---- set_availability transitions ---------------------------------------


def test_set_availability_opens_a_span(analyst, interviews):
    span = services.set_availability(
        analyst, interviews, Status.YES,
        on_date=_dt.date(2026, 9, 1), source=AvailabilitySpan.Source.IMPORT,
    )
    assert span.is_open
    assert span.status == Status.YES
    assert services.current_status(analyst, interviews) == Status.YES


def test_changing_status_closes_old_span_and_opens_new(analyst, interviews):
    services.set_availability(analyst, interviews, Status.YES, on_date=_dt.date(2026, 9, 1))
    services.set_availability(analyst, interviews, Status.NO, on_date=_dt.date(2027, 1, 1))

    spans = list(
        AvailabilitySpan.objects.filter(profile=analyst, function=interviews)
        .order_by("start_date")
    )
    assert len(spans) == 2
    assert spans[0].status == Status.YES
    assert spans[0].end_date == _dt.date(2026, 12, 31)  # closed day before the change
    assert spans[1].status == Status.NO
    assert spans[1].is_open
    assert services.current_status(analyst, interviews) == Status.NO


def test_idempotent_when_status_and_note_unchanged(analyst, interviews):
    first = services.set_availability(analyst, interviews, Status.YES, note="ok")
    again = services.set_availability(analyst, interviews, Status.YES, note="ok")
    assert first.pk == again.pk
    assert AvailabilitySpan.objects.filter(profile=analyst, function=interviews).count() == 1


def test_note_change_is_recorded_as_new_span(analyst, interviews):
    services.set_availability(analyst, interviews, Status.YES, note="")
    services.set_availability(analyst, interviews, Status.YES, note="Interviews OK Sept 2026")
    assert AvailabilitySpan.objects.filter(profile=analyst, function=interviews).count() == 2
    assert services.current_status(analyst, interviews) == Status.YES


def test_unknown_is_default_when_never_set(analyst, interviews):
    assert services.current_status(analyst, interviews) == Status.UNKNOWN


def test_current_map_returns_open_spans_only(analyst, interviews):
    advisor = AnalystFunction.objects.get(slug="advisor")
    services.set_availability(analyst, interviews, Status.YES)
    services.set_availability(analyst, advisor, Status.NO)
    mapping = services.current_map(analyst)
    assert mapping == {interviews.id: Status.YES, advisor.id: Status.NO}


# ---- The one-open-span invariant -----------------------------------------


def test_db_constraint_forbids_two_open_spans(analyst, interviews):
    AvailabilitySpan.objects.create(
        profile=analyst, function=interviews, status=Status.YES,
        start_date=_dt.date(2026, 9, 1),
    )
    with pytest.raises(IntegrityError):
        AvailabilitySpan.objects.create(
            profile=analyst, function=interviews, status=Status.NO,
            start_date=_dt.date(2026, 10, 1),
        )


# ---- coverage_fraction (credit) ------------------------------------------


def test_coverage_full_year(analyst, interviews):
    services.set_availability(analyst, interviews, Status.YES, on_date=_dt.date(2026, 9, 1))
    # Available across the whole AY 2026-2027 window, asked about after it ends.
    frac = services.coverage_fraction(
        analyst, interviews, "2026-2027", as_of=_dt.date(2027, 9, 1)
    )
    assert frac == pytest.approx(1.0)


def test_coverage_half_year(analyst, interviews):
    services.set_availability(analyst, interviews, Status.YES, on_date=_dt.date(2026, 9, 1))
    services.set_availability(analyst, interviews, Status.NO, on_date=_dt.date(2027, 3, 1))
    frac = services.coverage_fraction(
        analyst, interviews, "2026-2027", as_of=_dt.date(2027, 9, 1)
    )
    # Sept 1 2026 → Mar 1 2027 is roughly half of a Sept→Sept year.
    assert 0.45 < frac < 0.55


def test_coverage_open_span_accrues_only_to_as_of(analyst, interviews):
    services.set_availability(analyst, interviews, Status.YES, on_date=_dt.date(2026, 9, 1))
    # Halfway through the year: only the elapsed portion counts.
    frac = services.coverage_fraction(
        analyst, interviews, "2026-2027", as_of=_dt.date(2027, 3, 1)
    )
    assert 0.45 < frac < 0.55


def test_coverage_upcoming_year_is_zero(analyst, interviews):
    services.set_availability(analyst, interviews, Status.YES, on_date=_dt.date(2026, 6, 1))
    frac = services.coverage_fraction(
        analyst, interviews, "2026-2027", as_of=_dt.date(2026, 6, 15)
    )
    assert frac == 0.0


def test_coverage_ignores_non_yes_status(analyst, interviews):
    services.set_availability(analyst, interviews, Status.NO, on_date=_dt.date(2026, 9, 1))
    frac = services.coverage_fraction(
        analyst, interviews, "2026-2027", as_of=_dt.date(2027, 9, 1)
    )
    assert frac == 0.0


# ---- Eligibility ----------------------------------------------------------


def test_only_analysts_are_eligible(analyst):
    assert services.is_eligible(analyst) is True
    assert analyst in services.eligible_profiles()


def test_candidate_is_not_eligible():
    user = User.objects.create_user(email="c@example.com", password="pw")
    user.profile.role = Profile.Role.CANDIDATE
    user.profile.save()
    assert services.is_eligible(user.profile) is False
    assert user.profile not in services.eligible_profiles()
