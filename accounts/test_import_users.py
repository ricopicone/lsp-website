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
        "email,first_name,last_name,role,is_faculty,notes\n"
        "carla@example.com,Carla,Diaz,analyst,yes,Faculty analyst\n",
    )
    call_command("import_users", str(csv_path), stdout=StringIO())

    carla = User.objects.get(email="carla@example.com")
    assert carla.first_name == "Carla"
    assert carla.last_name == "Diaz"
    assert carla.profile.role == Profile.Role.ANALYST
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
    csv_path = _write_csv(tmp_path, "email,not_a_column\nu@example.com,x\n")
    with pytest.raises(CommandError, match="unknown column"):
        call_command("import_users", str(csv_path), stdout=StringIO())


@pytest.mark.django_db
def test_missing_file_errors(tmp_path):
    with pytest.raises(CommandError, match="File not found"):
        call_command(
            "import_users", str(tmp_path / "nope.csv"), stdout=StringIO()
        )


@pytest.mark.django_db
def test_update_skips_role_elevation_when_owing_tuition(tmp_path):
    """Update path: elevate owing candidate to analyst → role unchanged, fields updated, warning."""
    from datetime import date
    from decimal import Decimal

    from payments.models import TuitionEnrollment, TuitionPeriod

    # Create an existing candidate who owes tuition
    user = User.objects.create_user(email="owing@example.com", first_name="Old")
    user.profile.role = Profile.Role.CANDIDATE
    user.profile.save()

    # Clean up any default periods
    TuitionPeriod.objects.all().delete()

    # Create a tuition period and enroll them (with status COMMITTED)
    tp = TuitionPeriod.objects.create(
        name="AY 2025-2026", slug="t-2025", start_date=date(2025, 9, 1),
        end_date=date(2026, 8, 31), decision_due_date=date(2025, 8, 31),
        tuition_amount=Decimal("2000"))
    TuitionEnrollment.objects.create(
        user=user, tuition_period=tp, status=TuitionEnrollment.Status.COMMITTED,
        source="staff")

    # Import CSV that tries to elevate them to analyst and update first_name
    csv_path = tmp_path / "users.csv"
    csv_path.write_text(
        "email,first_name,role\nowing@example.com,New,analyst\n",
        encoding="utf-8"
    )
    err = StringIO()
    out = StringIO()
    call_command("import_users", str(csv_path), "--update", stdout=out, stderr=err)

    # Role should NOT have changed (stayed candidate)
    user.refresh_from_db()
    assert user.profile.role == Profile.Role.CANDIDATE
    # But first_name SHOULD have updated
    assert user.first_name == "New"
    # And there should be a warning in stderr
    stderr_text = err.getvalue()
    assert "warning" in stderr_text
    assert "owing@example.com" in stderr_text
    assert "role elevation to analyst skipped" in stderr_text


@pytest.mark.django_db
def test_update_allows_role_elevation_when_tuition_settled(tmp_path):
    """Update path: elevate candidate with 4 paid years to analyst → role updates."""
    from datetime import date, datetime
    from datetime import timezone as tz
    from decimal import Decimal

    from payments.models import Payment, TuitionEnrollment, TuitionPeriod

    # Create a candidate with 4 fully-paid tuition years
    user = User.objects.create_user(email="settled@example.com", first_name="Old")
    user.profile.role = Profile.Role.CANDIDATE
    user.profile.save()

    # Clean up any default periods
    TuitionPeriod.objects.all().delete()

    # Create 4 tuition periods and enroll (all COMMITTED)
    for i in range(4):
        start_year = 2021 + i
        tp = TuitionPeriod.objects.create(
            name=f"AY {start_year}-{start_year + 1}",
            slug=f"t-{start_year}",
            start_date=date(start_year, 9, 1),
            end_date=date(start_year + 1, 8, 31),
            decision_due_date=date(start_year, 8, 31),
            tuition_amount=Decimal("2000"))
        TuitionEnrollment.objects.create(
            user=user, tuition_period=tp, status=TuitionEnrollment.Status.COMMITTED,
            source="staff")

    # Create a payment covering all 4 years (8000 total)
    p = Payment.objects.create(
        user=user, payment_type=Payment.Type.TUITION, amount=Decimal("8000"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE)
    Payment.objects.filter(pk=p.pk).update(paid_at=datetime(2025, 10, 1, tzinfo=tz.utc))

    # Import CSV that elevates them to analyst and updates first_name
    csv_path = tmp_path / "users.csv"
    csv_path.write_text(
        "email,first_name,role\nsettled@example.com,New,analyst\n",
        encoding="utf-8"
    )
    err = StringIO()
    out = StringIO()
    call_command("import_users", str(csv_path), "--update", stdout=out, stderr=err)

    # Role SHOULD have changed to analyst
    user.refresh_from_db()
    assert user.profile.role == Profile.Role.ANALYST
    # And first_name SHOULD have updated
    assert user.first_name == "New"
    # No warning should be present
    stderr_text = err.getvalue()
    assert "warning" not in stderr_text or "owing" not in stderr_text.lower()
