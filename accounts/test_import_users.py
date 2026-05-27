"""Tests for the ``import_users`` management command (USR-3)."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from .models import Profile, User


def _write_csv(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "users.csv"
    path.write_text(content, encoding="utf-8")
    return path


@pytest.mark.django_db
def test_imports_minimal_csv(tmp_path):
    csv_path = _write_csv(
        tmp_path,
        "email\nalice@example.com\nbob@example.com\n",
    )
    out = StringIO()
    call_command("import_users", str(csv_path), stdout=out)

    assert User.objects.count() == 2
    alice = User.objects.get(email="alice@example.com")
    assert alice.profile.role == Profile.Role.EXTERNAL
    assert not alice.has_usable_password()
    assert "create 2" in out.getvalue()


@pytest.mark.django_db
def test_imports_full_row(tmp_path):
    csv_path = _write_csv(
        tmp_path,
        "email,first_name,last_name,role,tuition_paying,is_faculty,notes\n"
        "carla@example.com,Carla,Diaz,analyst,true,yes,Faculty analyst\n",
    )
    call_command("import_users", str(csv_path), stdout=StringIO())

    carla = User.objects.get(email="carla@example.com")
    assert carla.first_name == "Carla"
    assert carla.last_name == "Diaz"
    assert carla.profile.role == Profile.Role.ANALYST
    assert carla.profile.tuition_paying is True
    assert carla.profile.is_faculty is True
    assert carla.profile.notes == "Faculty analyst"


@pytest.mark.django_db
def test_is_faculty_defaults_false_when_column_absent(tmp_path):
    csv_path = _write_csv(tmp_path, "email\nstudent@example.com\n")
    call_command("import_users", str(csv_path), stdout=StringIO())
    assert User.objects.get(email="student@example.com").profile.is_faculty is False


@pytest.mark.django_db
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("analyst", Profile.Role.ANALYST),
        ("Pre-candidate", Profile.Role.PRE_CANDIDATE),
        ("pre_candidate", Profile.Role.PRE_CANDIDATE),
        ("Prospective Applicant", Profile.Role.PROSPECTIVE_APPLICANT),
    ],
)
def test_role_normalization(tmp_path, raw, expected):
    csv_path = _write_csv(
        tmp_path, f"email,role\nuser@example.com,{raw}\n"
    )
    call_command("import_users", str(csv_path), stdout=StringIO())
    assert User.objects.get(email="user@example.com").profile.role == expected


@pytest.mark.django_db
def test_dry_run_makes_no_changes(tmp_path):
    csv_path = _write_csv(tmp_path, "email\nghost@example.com\n")
    out = StringIO()
    call_command("import_users", str(csv_path), "--dry-run", stdout=out)

    assert User.objects.count() == 0
    assert "Would create 1" in out.getvalue()


@pytest.mark.django_db
def test_skips_existing_by_default(tmp_path):
    User.objects.create_user(email="alice@example.com", first_name="Old")
    csv_path = _write_csv(
        tmp_path,
        "email,first_name\nalice@example.com,New\n",
    )
    out = StringIO()
    call_command("import_users", str(csv_path), stdout=out)

    assert User.objects.get(email="alice@example.com").first_name == "Old"
    assert "skip 1" in out.getvalue()


@pytest.mark.django_db
def test_update_flag_updates_existing(tmp_path):
    User.objects.create_user(email="alice@example.com", first_name="Old")
    csv_path = _write_csv(
        tmp_path,
        "email,first_name,role\nalice@example.com,New,member\n",
    )
    call_command("import_users", str(csv_path), "--update", stdout=StringIO())

    alice = User.objects.get(email="alice@example.com")
    assert alice.first_name == "New"
    assert alice.profile.role == Profile.Role.MEMBER


@pytest.mark.django_db
def test_email_case_is_deduped(tmp_path):
    User.objects.create_user(email="alice@example.com")
    csv_path = _write_csv(tmp_path, "email\nAlice@Example.com\n")
    out = StringIO()
    call_command("import_users", str(csv_path), stdout=out)

    assert User.objects.count() == 1
    assert "skip 1" in out.getvalue()


@pytest.mark.django_db
def test_row_errors_roll_back_everything(tmp_path):
    csv_path = _write_csv(
        tmp_path,
        "email,role\n"
        "good@example.com,member\n"
        "bad-email,member\n",
    )
    err = StringIO()
    with pytest.raises(CommandError):
        call_command("import_users", str(csv_path), stdout=StringIO(), stderr=err)

    assert User.objects.count() == 0
    assert "line 3" in err.getvalue()


@pytest.mark.django_db
def test_unknown_role_is_an_error(tmp_path):
    csv_path = _write_csv(
        tmp_path, "email,role\nuser@example.com,not_a_role\n"
    )
    err = StringIO()
    with pytest.raises(CommandError):
        call_command("import_users", str(csv_path), stdout=StringIO(), stderr=err)

    assert User.objects.count() == 0
    assert "unknown role" in err.getvalue()


@pytest.mark.django_db
def test_missing_required_column(tmp_path):
    csv_path = _write_csv(tmp_path, "first_name\nAlice\n")
    with pytest.raises(CommandError, match="missing required column"):
        call_command("import_users", str(csv_path), stdout=StringIO())


@pytest.mark.django_db
def test_unknown_column_rejected(tmp_path):
    csv_path = _write_csv(tmp_path, "email,phone\nu@example.com,555\n")
    with pytest.raises(CommandError, match="unknown column"):
        call_command("import_users", str(csv_path), stdout=StringIO())


@pytest.mark.django_db
def test_missing_file_errors(tmp_path):
    with pytest.raises(CommandError, match="File not found"):
        call_command(
            "import_users", str(tmp_path / "nope.csv"), stdout=StringIO()
        )
