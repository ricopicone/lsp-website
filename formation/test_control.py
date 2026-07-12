import datetime as dt

import pytest

from accounts.models import User
from formation.models import ControlAnalysis, FormationSettings


@pytest.mark.django_db
def test_closed_entry_duration_in_years():
    u = User.objects.create_user(email="m@x.test")
    ca = ControlAnalysis.objects.create(
        member=u, supervisor_name="Dr Ferenczi", modality="remote",
        start_date=dt.date(2020, 1, 1), end_date=dt.date(2023, 1, 1),
    )
    assert round(ca.duration_years, 1) == 3.0


@pytest.mark.django_db
def test_ongoing_entry_counts_to_today(settings):
    u = User.objects.create_user(email="m2@x.test")
    ca = ControlAnalysis.objects.create(
        member=u, supervisor_name="Dr Klein", modality="in_person",
        start_date=dt.date.today() - dt.timedelta(days=365),
    )
    assert 0.9 < ca.duration_years < 1.1


@pytest.mark.django_db
def test_total_years_sums_entries():
    u = User.objects.create_user(email="m3@x.test")
    for s, e in [((2018, 1, 1), (2019, 1, 1)), ((2019, 1, 1), (2021, 1, 1))]:
        ControlAnalysis.objects.create(
            member=u, supervisor_name="S", modality="remote",
            start_date=dt.date(*s), end_date=dt.date(*e),
        )
    assert round(ControlAnalysis.years_for(u), 1) == 3.0


@pytest.mark.django_db
def test_settings_default_target_is_six():
    assert FormationSettings.load().control_years_target == 6


@pytest.mark.django_db
def test_control_requirement_tag_defaults_four_year():
    u = User.objects.create_user(email="t@example.com", password="x")
    ca = ControlAnalysis.objects.create(
        member=u, supervisor_name="S", start_date=dt.date(2020, 1, 1),
    )
    assert ca.requirement == ControlAnalysis.Requirement.FOUR_YEAR

    ca.requirement = ControlAnalysis.Requirement.TWO_YEAR
    ca.save()

    reloaded = ControlAnalysis.objects.get(pk=ca.pk)
    assert reloaded.requirement == "two_year"
