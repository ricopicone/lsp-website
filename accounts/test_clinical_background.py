import pytest

from accounts.models import Profile, User

pytestmark = pytest.mark.django_db


def _user(email, role):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = role
    u.profile.save()
    return u


def test_default_background_is_unreviewed():
    u = _user("new@example.com", Profile.Role.PRE_CANDIDATE)
    assert u.profile.formation_background == Profile.FormationBackground.UNREVIEWED
    assert u.profile.control_requirement() is None


def test_clinical_requirement_two_analyses():
    u = _user("clin@example.com", Profile.Role.ANALYST)
    u.profile.formation_background = Profile.FormationBackground.CLINICAL
    assert u.profile.control_requirement() == {"four_year": 1, "two_year": 1}


def test_academic_requirement_three_analyses():
    u = _user("acad@example.com", Profile.Role.PRE_CANDIDATE)
    u.profile.formation_background = Profile.FormationBackground.ACADEMIC
    assert u.profile.control_requirement() == {"four_year": 1, "two_year": 2}
