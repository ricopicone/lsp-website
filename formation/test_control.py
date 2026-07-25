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
def test_settings_default_thresholds_are_four_and_two():
    settings_ = FormationSettings.load()
    assert settings_.four_year_threshold == 4
    assert settings_.two_year_threshold == 2


def test_control_progress_fills_slots_by_longest_per_tag(db):
    import datetime as dt

    from accounts.models import Profile, User
    from formation.control import control_progress
    from formation.models import ControlAnalysis

    u = User.objects.create_user(email="p@example.com", password="x")
    u.profile.role = Profile.Role.PRE_CANDIDATE  # academic -> 2 two-year slots
    u.profile.formation_background = Profile.FormationBackground.ACADEMIC
    u.profile.save()

    today = dt.date.today()
    # A 5-year four-year entry, and two two-year entries (3yr and 1yr).
    ControlAnalysis.objects.create(
        member=u, supervisor_name="Long", requirement="four_year",
        start_date=today - dt.timedelta(days=int(365.25 * 5)),
    )
    ControlAnalysis.objects.create(
        member=u, supervisor_name="Mid", requirement="two_year",
        start_date=today - dt.timedelta(days=int(365.25 * 3)),
    )
    ControlAnalysis.objects.create(
        member=u, supervisor_name="Short", requirement="two_year",
        start_date=today - dt.timedelta(days=int(365.25 * 1)),
    )

    prog = control_progress(u)
    assert prog["total_target"] == 8            # 4 + 2*2
    assert prog["four_year"]["met"] is True
    assert prog["four_year"]["entry"].supervisor_name == "Long"
    assert len(prog["two_year"]) == 2
    assert prog["two_year"][0]["entry"].supervisor_name == "Mid"  # longest first
    assert prog["two_year"][0]["met"] is True                     # 3yr >= 2
    assert prog["two_year"][1]["met"] is False                    # 1yr < 2


def test_control_progress_total_years_is_float_with_no_entries(db):
    from accounts.models import Profile, User
    from formation.control import control_progress

    u = User.objects.create_user(email="nc@example.com", password="x")
    u.profile.role = Profile.Role.PRE_CANDIDATE
    u.profile.formation_background = Profile.FormationBackground.CLINICAL
    u.profile.save()

    prog = control_progress(u)
    assert isinstance(prog["total_years"], float)
    assert prog["total_years"] == 0.0


def test_control_progress_clinical_has_one_two_year_slot(db):
    from accounts.models import Profile, User
    from formation.control import control_progress

    u = User.objects.create_user(email="c@example.com", password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.formation_background = Profile.FormationBackground.CLINICAL
    u.profile.save()
    prog = control_progress(u)
    assert prog["total_target"] == 6            # 4 + 2*1
    assert len(prog["two_year"]) == 1


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


def test_control_progress_unreviewed_has_no_target(db):
    from accounts.models import Profile, User
    from formation.control import control_progress

    u = User.objects.create_user(email="unrev@example.com", password="x")
    u.profile.role = Profile.Role.PRE_CANDIDATE
    u.profile.formation_background = Profile.FormationBackground.UNREVIEWED
    u.profile.save()
    ControlAnalysis.objects.create(
        member=u, supervisor_name="S", requirement="four_year",
        start_date=dt.date.today() - dt.timedelta(days=int(365.25 * 2)),
    )

    prog = control_progress(u)
    assert prog["reviewed"] is False
    assert "total_target" not in prog
    assert prog["total_years"] == pytest.approx(2.0, abs=0.05)
