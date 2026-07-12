import importlib

import pytest

from accounts.models import Profile, User

pytestmark = pytest.mark.django_db

_backfill_module = importlib.import_module(
    "accounts.migrations.0034_profile_clinical_background"
)


def _user(email, role):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = role
    u.profile.save()
    return u


def test_clinical_requirement_two_analyses():
    u = _user("clin@example.com", Profile.Role.ANALYST)
    u.profile.clinical_background = True
    assert u.profile.control_requirement() == {"four_year": 1, "two_year": 1}


def test_academic_requirement_three_analyses():
    u = _user("acad@example.com", Profile.Role.PRE_CANDIDATE)
    assert u.profile.clinical_background is False
    assert u.profile.control_requirement() == {"four_year": 1, "two_year": 2}


def test_backfill_migration_sets_analysts_clinical_only():
    """Exercise the actual data migration function (not just the field
    default): existing analyst rows should flip to clinical_background=True;
    non-analyst rows should be left alone."""
    from django.apps import apps as real_apps

    analyst = _user("analyst-backfill@example.com", Profile.Role.ANALYST)
    candidate = _user("candidate-backfill@example.com", Profile.Role.CANDIDATE)
    assert analyst.profile.clinical_background is False
    assert candidate.profile.clinical_background is False

    _backfill_module.backfill_clinical(real_apps, schema_editor=None)

    analyst.profile.refresh_from_db()
    candidate.profile.refresh_from_db()
    assert analyst.profile.clinical_background is True
    assert candidate.profile.clinical_background is False
