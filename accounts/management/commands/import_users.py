"""Bulk-import known users from a CSV file (USR-3).

Required column: ``email``.
Optional columns: ``first_name``, ``last_name``, ``role``,
``tuition_paying``, ``notes``.

Imported users are created with an unusable password. Once email
delivery is configured (Amazon SES), they set a password through the
standard password-reset flow. No invitation emails are sent from this
command.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from django.contrib.auth.models import BaseUserManager
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction

from accounts.models import Profile, User

REQUIRED_COLUMNS = {"email"}
OPTIONAL_COLUMNS = {
    "first_name",
    "last_name",
    "role",
    "tuition_paying",
    "is_faculty",
    "notes",
}
ALL_COLUMNS = REQUIRED_COLUMNS | OPTIONAL_COLUMNS

_TRUTHY = {"true", "yes", "y", "1", "t"}
_FALSY = {"false", "no", "n", "0", "f"}


def _normalize_role(value: str) -> str:
    """Map flexible inputs (``'Pre-candidate'``, ``'pre_candidate'``) to a Role value."""
    cleaned = value.strip().lower().replace("-", "_").replace(" ", "_")
    valid = {choice.value for choice in Profile.Role}
    if cleaned not in valid:
        raise ValueError(
            f"unknown role {value!r}; expected one of: {', '.join(sorted(valid))}"
        )
    return cleaned


def _parse_bool(value: str) -> bool:
    cleaned = value.strip().lower()
    if cleaned in _TRUTHY:
        return True
    if cleaned in _FALSY:
        return False
    raise ValueError(f"cannot parse {value!r} as a boolean")


class Command(BaseCommand):
    help = (
        "Bulk-import users from a CSV file (USR-3). "
        "Columns: email (required), first_name, last_name, role, "
        "tuition_paying, is_faculty, notes. Imported users get an unusable "
        "password; they set one via password reset once email delivery is "
        "configured."
    )

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=Path, help="Path to the CSV file.")
        parser.add_argument(
            "--update",
            action="store_true",
            help="Update existing users (matched by email) instead of skipping them.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and report what would happen; make no changes.",
        )

    def handle(self, *args, csv_path: Path, update: bool, dry_run: bool, **opts):
        if not csv_path.exists():
            raise CommandError(f"File not found: {csv_path}")

        with csv_path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                raise CommandError("CSV is empty or has no header row.")
            fieldnames = {name.strip() for name in reader.fieldnames}
            missing = REQUIRED_COLUMNS - fieldnames
            if missing:
                raise CommandError(
                    f"CSV is missing required column(s): {', '.join(sorted(missing))}."
                )
            unknown = fieldnames - ALL_COLUMNS
            if unknown:
                raise CommandError(
                    f"CSV has unknown column(s): {', '.join(sorted(unknown))}. "
                    f"Allowed: {', '.join(sorted(ALL_COLUMNS))}."
                )
            rows = list(reader)

        created = updated = skipped = 0
        errors: list[str] = []

        with transaction.atomic():
            for line_no, row in enumerate(rows, start=2):  # header is line 1
                try:
                    created_, updated_, skipped_ = self._apply_row(row, update=update)
                    created += created_
                    updated += updated_
                    skipped += skipped_
                    if created_:
                        self.stdout.write(f"  line {line_no}: created {row['email']}")
                    elif updated_:
                        self.stdout.write(f"  line {line_no}: updated {row['email']}")
                    elif skipped_:
                        self.stdout.write(
                            f"  line {line_no}: skipped (exists) {row['email']}"
                        )
                except (ValueError, ValidationError) as exc:
                    msg = exc.messages[0] if isinstance(exc, ValidationError) else str(exc)
                    errors.append(f"line {line_no}: {msg}")

            if errors:
                for err in errors:
                    self.stderr.write(err)
                transaction.set_rollback(True)
                raise CommandError(
                    f"{len(errors)} row error(s); no changes were saved."
                )

            if dry_run:
                transaction.set_rollback(True)

        prefix = "Would " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}create {created}, update {updated}, "
                f"skip {skipped} (of {len(rows)} row(s))."
            )
        )

    def _apply_row(self, row: dict[str, str], *, update: bool) -> tuple[int, int, int]:
        """Apply one CSV row. Returns ``(created, updated, skipped)`` as 0/1 flags."""
        raw_email = (row.get("email") or "").strip()
        if not raw_email:
            raise ValueError("email is required")
        validate_email(raw_email)
        email = BaseUserManager.normalize_email(raw_email)
        row["email"] = email  # so logging shows the normalized form

        user_fields: dict[str, Any] = {}
        for key in ("first_name", "last_name"):
            val = (row.get(key) or "").strip()
            if val:
                user_fields[key] = val

        profile_fields: dict[str, Any] = {}
        if (val := (row.get("role") or "").strip()):
            profile_fields["role"] = _normalize_role(val)
        if (val := (row.get("tuition_paying") or "").strip()):
            profile_fields["tuition_paying"] = _parse_bool(val)
        if (val := (row.get("is_faculty") or "").strip()):
            profile_fields["is_faculty"] = _parse_bool(val)
        if (val := (row.get("notes") or "").strip()):
            profile_fields["notes"] = val

        existing = User.objects.filter(email__iexact=email).first()
        if existing is not None:
            if not update:
                return (0, 0, 1)
            for k, v in user_fields.items():
                setattr(existing, k, v)
            if user_fields:
                existing.save(update_fields=list(user_fields))
            if profile_fields:
                Profile.objects.filter(user=existing).update(**profile_fields)
            return (0, 1, 0)

        user = User.objects.create_user(email=email, password=None, **user_fields)
        if profile_fields:
            Profile.objects.filter(user=user).update(**profile_fields)
        return (1, 0, 0)
